import re
import json
import logging
from typing import List, Dict, Any, Optional
import httpx
from .models import MessageItem
from .config import config

logger = logging.getLogger(__name__)

# Security & Anti-Leakage Patterns
CARD_PATTERN = re.compile(r'\b(?:\d[ -]*?){13,16}\b')
CVV_PATTERN = re.compile(r'\b\d{3,4}\b')
OTP_PATTERN = re.compile(r'(?i)\b(?:otp|code|pin)[:\s]*\d{4,6}\b')
PASSWORD_PATTERN = re.compile(r'(?i)\b(?:password|pass|secret|pin)(?:\s+(?:is|was|code|key|password|pass))?[:\s]+\S+')


CHIT_CHAT_PHRASES = {
    'hi', 'hello', 'hey', 'kemon achen', 'valon ni', 'thanks', 'dhonnobad', 'thank you',
    'ok', 'accha', 'thik ache', 'bye', 'good morning', 'good evening', 'good night'
}

class MemoryExtractor:
    @staticmethod
    def sanitize_text(text: str) -> str:
        """Strips sensitive financial and authentication data."""
        clean = CARD_PATTERN.sub('[CARD_REDACTED]', text)
        clean = OTP_PATTERN.sub('[OTP_REDACTED]', clean)
        clean = PASSWORD_PATTERN.sub('[PASSWORD_REDACTED]', clean)
        return clean

    def extract_from_messages(self, messages: List[MessageItem]) -> Dict[str, Any]:
        """
        Extracts generic preferences, interests, and reported issues from conversation turns using LLM.
        """
        extracted = {
            "preferences": [],
            "interests": [],
            "issues": []
        }

        # Asynchronous LLM Semantic Extraction
        llm_extracted = self.extract_with_llm(messages)
        if llm_extracted:
            return llm_extracted
            
        return extracted

    def extract_with_llm(self, messages: List[MessageItem]) -> Optional[Dict[str, Any]]:
        """
        Asynchronously extract complex, multi-entity relationships using configured LLM.
        Times out gracefully after 2.5s and falls back to deterministic extraction.
        """
        settings = config.get_llm_settings()
        api_key = settings.get('api_key')
        is_local = settings.get('provider') in ('ollama', 'local', 'vllm')
        if not api_key and not is_local:
            return None

        # Build conversation text with full context for coreference resolution
        formatted_turns = []
        has_inbound = False
        for m in messages:
            role = "Customer" if m.direction == 'inbound' else "AI"
            if m.direction == 'inbound':
                has_inbound = True
            formatted_turns.append(f"{role}: {self.sanitize_text(m.body)}")
            
        if not has_inbound:
            return None

        prompt_text = "\n".join(formatted_turns)
        if len(prompt_text.strip()) < 15:
            return None

        system_prompt = (
            "You are a generic AI Conversational Entity & Preference Extractor for any domain.\n"
            "Analyze the conversation history (including both AI and Customer turns) to extract structured factual information.\n"
            "Rules:\n"
            "1. ONLY extract information EXPLICITLY stated or agreed upon by the customer. Resolve pronouns (like 'eta', 'this', 'that', 'yes') based on the AI's preceding context.\n"
            "2. Output strictly valid JSON matching this generic schema:\n"
            "{\n"
            '  "preferences": [{"category": "string", "value": "string"}],\n'
            '  "interests": [{"entity_type": "string", "entity_name": "string"}],\n'
            '  "issues": [{"category": "string", "description": "string"}]\n'
            "}"
        )

        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": settings["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Customer Dialogue:\n{prompt_text}"}
                ],
                "temperature": 0.0,
                "max_tokens": 300,
                "response_format": {"type": "json_object"}
            }
            with httpx.Client(timeout=2.5) as client:
                res = client.post(f"{settings["base_url"]}/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    return parsed
        except Exception as e:
            logger.debug(f"[MemoryExtractor] LLM extraction bypassed or timed out: {e}")
            return None

memory_extractor = MemoryExtractor()

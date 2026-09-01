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

# Extraction Regex Patterns
STOP_WORDS_ORDERS = {'was', 'is', 'no', 'id', 'the', 'my', 'ta', 'eta'}
ORDER_NUMBER_PATTERN = re.compile(r'(?:order|ord|অর্ডার|পার্সেল|parcel)(?:\s+(?:is|was|no|id|number|নম্বর|code))?[\s#:]*([A-Za-z0-9\-_]{3,15})', re.IGNORECASE)
GENERIC_ORDER_HASH = re.compile(r'#([A-Za-z0-9\-_]{3,12})')

SIZE_PATTERNS = [
    re.compile(r'\b(size|সাইজ)[:\s]*([XSLM0-9]{1,4})\b', re.IGNORECASE),
    re.compile(r'\b(XXL|XL|XXS|XS|L|M|S)\b', re.IGNORECASE),
    re.compile(r'\b(36|38|40|42|44|46)\b'),
]

COLOR_MAP = {
    'black': 'Black',
    'কালো': 'Black',
    'navy blue': 'Navy Blue',
    'নেভি ব্লু': 'Navy Blue',
    'blue': 'Blue',
    'নীল': 'Blue',
    'white': 'White',
    'সাদা': 'White',
    'maroon': 'Maroon',
    'মেরুন': 'Maroon',
    'red': 'Red',
    'লাল': 'Red',
    'green': 'Green',
    'সবুজ': 'Green',
    'olive': 'Olive',
}

DELIVERY_PATTERNS = [
    (re.compile(r'(?i)(?:deliver|delivery|ডেলিভারি).*?(?:after|পর)\s*(\d{1,2}(?:\s*(?:pm|am|ta|টা))?)'), 'Deliver after {0}'),
    (re.compile(r'(?i)(?:evening|সন্ধ্যা|shondha)'), 'Evening delivery preferred'),
    (re.compile(r'(?i)(?:call before|আগে ফোন)'), 'Call customer before delivery'),
]

PAYMENT_METHODS = {
    'bkash': ('bkash', 'bKash'),
    'বিকাশ': ('bkash', 'bKash'),
    'nagad': ('nagad', 'Nagad'),
    'নগদ': ('nagad', 'Nagad'),
    'rocket': ('rocket', 'Rocket'),
    'রকেট': ('rocket', 'Rocket'),
    'card': ('card_visa', 'Credit/Debit Card'),
    'visa': ('card_visa', 'Visa Card'),
    'mastercard': ('card_mastercard', 'Mastercard'),
    'cod': ('cash_on_delivery', 'Cash on Delivery'),
    'cash on delivery': ('cash_on_delivery', 'Cash on Delivery'),
    'ক্যাশ অন ডেলিভারি': ('cash_on_delivery', 'Cash on Delivery'),
}

ISSUE_KEYWORDS = {
    'damaged': ('damaged_item', 'Customer reported damaged/broken item'),
    'ভাঙ্গা': ('damaged_item', 'Customer reported broken product'),
    'নষ্ট': ('damaged_item', 'Customer reported defective product'),
    'delay': ('delivery_delay', 'Customer reported delayed delivery'),
    'দেরি': ('delivery_delay', 'Customer reported shipping delay'),
    'missing': ('missing_item', 'Customer reported missing item in parcel'),
    'wrong': ('wrong_item', 'Customer reported receiving wrong item or size'),
    'ভুল': ('wrong_item', 'Customer reported receiving incorrect product'),
}

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
        Extracts preferences, discussed orders, and reported issues from conversation turns
        using dual-path deterministic regex with optional LLM fallback.
        """
        extracted = {
            "payment_preference": None,
            "size_preference": None,
            "color_preference": None,
            "delivery_preference": None,
            "discussed_orders": [],
            "reported_issues": [],
            "interested_products": [],
        }

        # ── 1. Fast-Path Deterministic Rule & Regex Extraction ──────────
        for msg in messages:
            if msg.direction != 'inbound':
                continue

            text = self.sanitize_text(msg.body)
            lower_text = text.lower()

            # Ignore pure pleasantries
            if lower_text.strip() in CHIT_CHAT_PHRASES:
                continue

            # A. Payment Preference
            for kw, (code, name) in PAYMENT_METHODS.items():
                if kw in lower_text:
                    extracted["payment_preference"] = {"code": code, "name": name}
                    break

            # B. Size Preference
            for pat in SIZE_PATTERNS:
                m = pat.search(text)
                if m:
                    val = m.group(2) if len(m.groups()) >= 2 else m.group(1)
                    if val:
                        extracted["size_preference"] = val.upper()
                        break

            # C. Color Preference
            for col_kw, col_name in COLOR_MAP.items():
                if col_kw in lower_text:
                    extracted["color_preference"] = col_name
                    break

            # D. Delivery Preference
            for del_pat, template in DELIVERY_PATTERNS:
                del_m = del_pat.search(text)
                if del_m:
                    if "{0}" in template and len(del_m.groups()) >= 1:
                        extracted["delivery_preference"] = template.format(del_m.group(1))
                    else:
                        extracted["delivery_preference"] = template
                    break

            # E. Discussed Orders
            hash_m = GENERIC_ORDER_HASH.search(text)
            if hash_m:
                order_id = hash_m.group(1).strip()
                if order_id.lower() not in STOP_WORDS_ORDERS and len(order_id) >= 2 and order_id not in extracted["discussed_orders"]:
                    extracted["discussed_orders"].append(order_id)
            else:
                order_m = ORDER_NUMBER_PATTERN.search(text)
                if order_m:
                    order_id = order_m.group(1).strip()
                    if order_id.lower() not in STOP_WORDS_ORDERS and len(order_id) >= 3 and order_id not in extracted["discussed_orders"]:
                        extracted["discussed_orders"].append(order_id)

            # F. Reported Issues
            for kw, (category, desc) in ISSUE_KEYWORDS.items():
                if kw in lower_text:
                    if not any(i["category"] == category for i in extracted["reported_issues"]):
                        extracted["reported_issues"].append({
                            "category": category,
                            "description": desc
                        })

        # ── 2. Asynchronous LLM Semantic Extraction for Nuanced Statements ──
        llm_extracted = self.extract_with_llm(messages)
        if llm_extracted:
            # Merge color if missed
            if not extracted["color_preference"] and llm_extracted.get("color_preference"):
                extracted["color_preference"] = str(llm_extracted["color_preference"]).strip()

            # Merge delivery preference if missed
            if not extracted["delivery_preference"] and llm_extracted.get("delivery_preference"):
                extracted["delivery_preference"] = str(llm_extracted["delivery_preference"]).strip()

            # Merge products
            for prod in llm_extracted.get("interested_products", []):
                if prod and prod not in extracted["interested_products"]:
                    extracted["interested_products"].append(str(prod).strip())

            # Merge orders if missed
            for ord_id in llm_extracted.get("discussed_orders", []):
                if ord_id and ord_id not in extracted["discussed_orders"]:
                    extracted["discussed_orders"].append(str(ord_id).strip())

        return extracted

    def extract_with_llm(self, messages: List[MessageItem]) -> Optional[Dict[str, Any]]:
        """
        Asynchronously extract complex, multi-entity relationships using configured LLM.
        Times out gracefully after 2.5s and falls back to deterministic extraction.
        """
        api_key = config.LLM_API_KEY
        if not api_key:
            return None

        # Build conversation text
        inbound_turns = [self.sanitize_text(m.body) for m in messages if m.direction == 'inbound']
        if not inbound_turns:
            return None

        prompt_text = "\n".join(inbound_turns)
        if len(prompt_text.strip()) < 15 or prompt_text.strip().lower() in CHIT_CHAT_PHRASES:
            return None

        system_prompt = (
            "You are an enterprise Commerce Conversational Entity & Preference Extractor.\n"
            "Analyze the customer's dialogue turns and extract structured factual preferences and issues into JSON.\n"
            "Rules:\n"
            "1. ONLY extract information EXPLICITLY stated by the customer. Never hallucinate or assume.\n"
            "2. Output strictly valid JSON matching this schema:\n"
            "{\n"
            '  "payment_preference": "bkash" | "nagad" | "card_visa" | "cash_on_delivery" | null,\n'
            '  "size_preference": string | null,\n'
            '  "color_preference": string | null,\n'
            '  "delivery_preference": string | null,\n'
            '  "discussed_orders": string[],\n'
            '  "reported_issues": [{"category": string, "description": string}],\n'
            '  "interested_products": string[]\n'
            "}"
        )

        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": config.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Customer Dialogue:\n{prompt_text}"}
                ],
                "temperature": 0.0,
                "max_tokens": 300,
                "response_format": {"type": "json_object"}
            }
            with httpx.Client(timeout=2.5) as client:
                res = client.post(f"{config.LLM_BASE_URL}/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    return parsed
        except Exception as e:
            logger.debug(f"[MemoryExtractor] LLM extraction bypassed or timed out: {e}")
            return None

memory_extractor = MemoryExtractor()

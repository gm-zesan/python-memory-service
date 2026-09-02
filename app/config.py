import os
from typing import Dict, Any
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()

class MemoryConfig:
    # Service Info
    SERVICE_NAME: str = "python-memory-service"
    VERSION: str = "1.0.0"
    HOST: str = os.getenv("MEMORY_SERVICE_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("MEMORY_SERVICE_PORT", "8002"))

    # Neo4j Settings
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "secret1234")
    NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")
    NEO4J_MAX_CONNECTION_LIFETIME: int = int(os.getenv("NEO4J_MAX_CONNECTION_LIFETIME", "300"))
    NEO4J_MAX_CONNECTION_POOL_SIZE: int = int(os.getenv("NEO4J_MAX_CONNECTION_POOL_SIZE", "50"))

    # LLM Settings for Graphiti / Extraction (Provider Agnostic)
    LLM_PROVIDER: str = os.getenv("MEMORY_LLM_PROVIDER", "openrouter")
    LLM_API_KEY: str = os.getenv("OPENROUTER_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
    LLM_BASE_URL: str = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1")
    LLM_MODEL: str = os.getenv("MEMORY_LLM_MODEL", "openrouter/free")

    # Guardrails
    MAX_SUBGRAPH_EDGES: int = int(os.getenv("MAX_SUBGRAPH_EDGES", "5"))
    DEFAULT_MIN_RELEVANCE: float = float(os.getenv("DEFAULT_MIN_RELEVANCE", "0.50"))

    @classmethod
    def get_llm_settings(cls) -> Dict[str, Any]:
        provider = cls.LLM_PROVIDER.lower()
        if provider == "deepseek":
            return {
                "provider": "deepseek",
                "base_url": os.getenv("DEEPSEEK_URL", "https://api.deepseek.com"),
                "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            }
        elif provider == "openai":
            return {
                "provider": "openai",
                "base_url": os.getenv("OPENAI_URL", "https://api.openai.com/v1"),
                "api_key": os.getenv("OPENAI_API_KEY", ""),
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            }
        elif provider in ("ollama", "local", "vllm"):
            return {
                "provider": provider,
                "base_url": os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1"),
                "api_key": os.getenv("LOCAL_LLM_KEY", "ollama"),
                "model": os.getenv("LOCAL_LLM_MODEL", "llama3.2"),
            }
        else: # default openrouter
            return {
                "provider": "openrouter",
                "base_url": os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1"),
                "api_key": os.getenv("OPENROUTER_API_KEY", cls.LLM_API_KEY),
                "model": os.getenv("OPENROUTER_MODEL", cls.LLM_MODEL),
            }

config = MemoryConfig()

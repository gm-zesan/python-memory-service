import os
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

    # LLM Settings for Graphiti / Extraction
    LLM_PROVIDER: str = os.getenv("MEMORY_LLM_PROVIDER", "openrouter")
    LLM_API_KEY: str = os.getenv("OPENROUTER_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
    LLM_BASE_URL: str = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1")
    LLM_MODEL: str = os.getenv("MEMORY_LLM_MODEL", "openrouter/free")

    # Guardrails
    MAX_SUBGRAPH_EDGES: int = int(os.getenv("MAX_SUBGRAPH_EDGES", "5"))
    DEFAULT_MIN_RELEVANCE: float = float(os.getenv("DEFAULT_MIN_RELEVANCE", "0.50"))

config = MemoryConfig()

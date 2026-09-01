from typing import List, Optional, Dict, Any
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from datetime import datetime

class MessageItem(BaseModel):
    direction: str = Field(..., description="'inbound' or 'outbound'")
    body: str = Field(..., description="Message text")
    timestamp: Optional[str] = Field(None, description="ISO timestamp string")

class MemoryIngestRequest(BaseModel):
    workspace_id: int = Field(..., description="Tenant workspace ID")
    customer_id: str = Field(..., description="Unique customer identifier")
    conversation_id: str = Field(..., description="Conversation session UUID")
    channel: str = Field("web", description="Channel name (facebook, whatsapp, web, etc.)")
    messages: List[MessageItem] = Field(..., description="Dialogue turns in chronological order")

class ExtractedEntityItem(BaseModel):
    label: str
    properties: Dict[str, Any]

class ExtractedEdgeItem(BaseModel):
    relation: str
    target_label: str
    target_properties: Dict[str, Any]
    edge_properties: Dict[str, Any]

class MemoryIngestResponse(BaseModel):
    success: bool
    status: str
    conversation_id: str
    entities_extracted: int = 0
    edges_created: int = 0
    entities: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

class MemorySearchRequest(BaseModel):
    workspace_id: int
    customer_id: str
    conversation_id: Optional[str] = None
    query: str
    limit: int = 5
    min_relevance: float = 0.50

class MemorySearchResultItem(BaseModel):
    type: str = Field(..., description="'preference', 'historical_action', 'issue', 'topic'")
    subject: str = "Customer"
    relation: str
    object: str
    attributes: Dict[str, Any] = {}
    status: str = "current"
    confidence: float = 1.0

class MemorySearchResponse(BaseModel):
    success: bool
    customer_id: str
    has_memories: bool
    memories_count: int
    memories: List[MemorySearchResultItem]
    formatted_memory_context: str
    latency_ms: float

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    neo4j: Dict[str, Any]

class CustomerMemoryResponse(BaseModel):
    customer_id: str
    workspace_id: int
    nodes_count: int
    edges_count: int
    memories: List[MemorySearchResultItem]

class DeleteMemoryResponse(BaseModel):
    success: bool
    deleted_nodes: int = 0
    deleted_edges: int = 0
    message: str

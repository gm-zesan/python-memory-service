import time
import logging
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, status, Header
from .models import (
    HealthResponse,
    MemoryIngestRequest,
    MemoryIngestResponse,
    MemorySearchRequest,
    MemorySearchResponse,
)
from .config import config
from .neo4j_client import neo4j_client
from .memory_extractor import memory_extractor
from .memory_retriever import memory_retriever

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
def get_health():
    neo4j_status = neo4j_client.health_check()
    service_status = "ok" if neo4j_status.get("status") == "connected" else "degraded"
    return HealthResponse(
        status=service_status,
        service=config.SERVICE_NAME,
        version=config.VERSION,
        neo4j=neo4j_status,
    )

@router.post("/memory/ingest", response_model=MemoryIngestResponse)
def ingest_conversation_memory(req: MemoryIngestRequest):
    t_start = time.time()
    try:
        # 1. Upsert customer and conversation nodes
        neo4j_client.upsert_customer_and_conversation(
            workspace_id=req.workspace_id,
            customer_id=req.customer_id,
            conversation_id=req.conversation_id,
            channel=req.channel,
        )

        # 2. Extract preferences, orders, issues from message history
        extracted = memory_extractor.extract_from_messages(req.messages)

        edges_created = 0

        # Set payment preference
        if extracted["payment_preference"]:
            neo4j_client.set_payment_preference(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                payment_code=extracted["payment_preference"]["code"],
                payment_name=extracted["payment_preference"]["name"],
            )
            edges_created += 1

        # Set size preference
        if extracted["size_preference"]:
            neo4j_client.set_size_preference(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                size_value=extracted["size_preference"],
            )
            edges_created += 1

        # Record discussed orders
        for order_id in extracted["discussed_orders"]:
            neo4j_client.record_discussed_order(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                order_id=order_id,
            )
            edges_created += 1

        # Record reported issues
        for issue in extracted["reported_issues"]:
            neo4j_client.record_reported_issue(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                category=issue["category"],
                description=issue["description"],
            )
            edges_created += 1

        return MemoryIngestResponse(
            success=True,
            status="processed",
            conversation_id=req.conversation_id,
            entities_extracted=len(extracted["discussed_orders"]) + len(extracted["reported_issues"]) + (1 if extracted["payment_preference"] else 0) + (1 if extracted["size_preference"] else 0),
            edges_created=edges_created,
            entities=[{"type": k, "data": v} for k, v in extracted.items() if v],
            edges=[],
        )
    except Exception as e:
        logger.error(f"[API] Memory ingest error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest conversation memory: {str(e)}",
        )

@router.post("/memory/search", response_model=MemorySearchResponse)
def search_memory(req: MemorySearchRequest):
    t_start = time.time()
    try:
        result = memory_retriever.search_memories(
            workspace_id=req.workspace_id,
            customer_id=req.customer_id,
            limit=req.limit,
        )
        latency_ms = round((time.time() - t_start) * 1000, 2)

        return MemorySearchResponse(
            success=True,
            customer_id=req.customer_id,
            has_memories=result["has_memories"],
            memories_count=result["memories_count"],
            memories=result["memories"],
            formatted_memory_context=result["formatted_memory_context"],
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.error(f"[API] Memory search error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Memory search failed: {str(e)}",
        )

@router.delete("/memory/customer/{customer_id}")
def delete_customer_memory(customer_id: str, x_workspace_id: int = Header(1, alias="X-Workspace-Id")):
    try:
        res = neo4j_client.delete_customer_memory(workspace_id=x_workspace_id, customer_id=customer_id)
        return {
            "success": True,
            "deleted_customer_id": customer_id,
            "detached_edges_count": res["detached_edges"],
        }
    except Exception as e:
        logger.error(f"[API] Delete customer memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/memory/conversation/{conversation_id}")
def delete_conversation_memory(conversation_id: str, x_workspace_id: int = Header(1, alias="X-Workspace-Id")):
    try:
        res = neo4j_client.delete_conversation_memory(workspace_id=x_workspace_id, conversation_id=conversation_id)
        return {
            "success": True,
            "deleted_conversation_id": conversation_id,
            "deleted_edges_count": res["deleted_edges"],
        }
    except Exception as e:
        logger.error(f"[API] Delete conversation memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

import time
import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Header, status
from .models import (
    HealthResponse,
    MemoryIngestRequest,
    MemoryIngestResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    CustomerMemoryResponse,
    DeleteMemoryResponse,
)
from .neo4j_client import neo4j_client
from .memory_extractor import memory_extractor
from .memory_retriever import memory_retriever
from .config import config

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health", response_model=HealthResponse)
def health():
    neo4j_health = neo4j_client.health_check()
    status_str = "ok" if neo4j_health["status"] == "connected" else "degraded"
    return HealthResponse(
        status=status_str,
        service=config.SERVICE_NAME,
        version=config.VERSION,
        neo4j=neo4j_health,
    )

@router.post("/memory/ingest", response_model=MemoryIngestResponse)
def ingest_memory(req: MemoryIngestRequest):
    try:
        # 1. Upsert customer and conversation nodes & link with [:PARTICIPATED_IN]
        neo4j_client.upsert_customer_and_conversation(
            workspace_id=req.workspace_id,
            customer_id=req.customer_id,
            conversation_id=req.conversation_id,
            channel=req.channel,
        )

        # 2. Extract structured entities, preferences, orders, issues (deterministic + LLM)
        extracted = memory_extractor.extract_from_messages(req.messages)

        edges_created = 1  # [:PARTICIPATED_IN]

        # Set payment preference
        if extracted.get("payment_preference"):
            neo4j_client.set_payment_preference(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                payment_code=extracted["payment_preference"]["code"],
                payment_name=extracted["payment_preference"]["name"],
            )
            edges_created += 1

        # Set size preference
        if extracted.get("size_preference"):
            neo4j_client.set_size_preference(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                size_value=extracted["size_preference"],
            )
            edges_created += 1

        # Set color preference
        if extracted.get("color_preference"):
            neo4j_client.set_color_preference(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                color_value=extracted["color_preference"],
            )
            edges_created += 1

        # Set delivery preference
        if extracted.get("delivery_preference"):
            neo4j_client.set_delivery_preference(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                delivery_instruction=extracted["delivery_preference"],
            )
            edges_created += 1

        # Record discussed orders
        for order_id in extracted.get("discussed_orders", []):
            neo4j_client.record_discussed_order(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                order_id=order_id,
            )
            edges_created += 1

        # Record product interests
        for prod_title in extracted.get("interested_products", []):
            neo4j_client.record_product_interest(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                product_title=prod_title,
            )
            edges_created += 1

        # Record reported issues
        for issue in extracted.get("reported_issues", []):
            neo4j_client.record_reported_issue(
                workspace_id=req.workspace_id,
                customer_id=req.customer_id,
                conversation_id=req.conversation_id,
                category=issue["category"],
                description=issue["description"],
            )
            edges_created += 1

        total_entities = (
            len(extracted.get("discussed_orders", []))
            + len(extracted.get("reported_issues", []))
            + len(extracted.get("interested_products", []))
            + (1 if extracted.get("payment_preference") else 0)
            + (1 if extracted.get("size_preference") else 0)
            + (1 if extracted.get("color_preference") else 0)
            + (1 if extracted.get("delivery_preference") else 0)
        )

        return MemoryIngestResponse(
            success=True,
            status="processed",
            conversation_id=req.conversation_id,
            entities_extracted=total_entities,
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
        search_result = memory_retriever.search_memories(
            workspace_id=req.workspace_id,
            customer_id=req.customer_id,
            query=req.query,
            limit=req.limit,
            min_relevance=req.min_relevance,
        )
        latency_ms = round((time.time() - t_start) * 1000, 2)
        return MemorySearchResponse(
            success=True,
            customer_id=req.customer_id,
            has_memories=search_result["has_memories"],
            memories_count=search_result["memories_count"],
            memories=search_result["memories"],
            formatted_memory_context=search_result["formatted_memory_context"],
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.error(f"[API] Memory search error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search conversation memory: {str(e)}",
        )

@router.get("/memory/customer/{customer_id}", response_model=CustomerMemoryResponse)
def get_customer_memory(customer_id: str, x_workspace_id: int = Header(..., alias="X-Workspace-Id")):
    try:
        search_result = memory_retriever.search_memories(
            workspace_id=x_workspace_id,
            customer_id=customer_id,
            limit=20,
        )
        return CustomerMemoryResponse(
            customer_id=customer_id,
            workspace_id=x_workspace_id,
            nodes_count=search_result["memories_count"],
            edges_count=search_result["memories_count"],
            memories=search_result["memories"],
        )
    except Exception as e:
        logger.error(f"[API] Get customer memory error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve customer memory: {str(e)}",
        )

@router.delete("/memory/customer/{customer_id}", response_model=DeleteMemoryResponse)
def delete_customer_memory(customer_id: str, x_workspace_id: int = Header(..., alias="X-Workspace-Id")):
    try:
        res = neo4j_client.delete_customer_memory(
            workspace_id=x_workspace_id,
            customer_id=customer_id,
        )
        return DeleteMemoryResponse(
            success=True,
            deleted_nodes=0,
            deleted_edges=res["detached_edges"],
            message=f"Purged memories for customer {customer_id}",
        )
    except Exception as e:
        logger.error(f"[API] Delete customer memory error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete customer memory: {str(e)}",
        )

@router.delete("/memory/conversation/{conversation_id}", response_model=DeleteMemoryResponse)
def delete_conversation_memory(conversation_id: str, x_workspace_id: int = Header(..., alias="X-Workspace-Id")):
    try:
        res = neo4j_client.delete_conversation_memory(
            workspace_id=x_workspace_id,
            conversation_id=conversation_id,
        )
        return DeleteMemoryResponse(
            success=True,
            deleted_nodes=1,
            deleted_edges=res["deleted_edges"],
            message=f"Purged conversation session {conversation_id}",
        )
    except Exception as e:
        logger.error(f"[API] Delete conversation memory error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete conversation memory: {str(e)}",
        )

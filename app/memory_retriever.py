import logging
from typing import Dict, Any, List
from .neo4j_client import neo4j_client
from .models import MemorySearchResultItem

logger = logging.getLogger(__name__)

class MemoryRetriever:
    def search_memories(
        self,
        workspace_id: int,
        customer_id: str,
        limit: int = 5
    ) -> Dict[str, Any]:
        raw_memories = neo4j_client.search_customer_memories(
            workspace_id=workspace_id,
            customer_id=customer_id,
            limit=limit
        )

        formatted_lines = []
        items: List[MemorySearchResultItem] = []

        for m in raw_memories:
            rel = m.get("relation")
            obj = m.get("object")
            status = m.get("status", "current")
            status_tag = f" ({status})" if status == "past" else ""

            if rel == "PREFERS":
                formatted_lines.append(f"- Preferred Payment: {obj}{status_tag}")
            elif rel == "PREFERS_SIZE":
                formatted_lines.append(f"- Preferred Size: {obj}{status_tag}")
            elif rel == "DISCUSSED":
                formatted_lines.append(f"- Previously Discussed Order: #{obj}")
            elif rel == "INTERESTED_IN":
                formatted_lines.append(f"- Showed Interest in: {obj}")
            elif rel == "REPORTED":
                desc = m.get("description", obj)
                formatted_lines.append(f"- Previous Support Issue: {desc}")

            items.append(MemorySearchResultItem(
                type=m.get("type", "preference"),
                subject="Customer",
                relation=rel,
                object=str(obj),
                attributes=m,
                status=status,
                confidence=float(m.get("confidence", 1.0))
            ))

        formatted_context = ""
        if formatted_lines:
            formatted_context = "Customer Historical Preferences & Context:\n" + "\n".join(formatted_lines)

        return {
            "has_memories": len(items) > 0,
            "memories_count": len(items),
            "memories": items,
            "formatted_memory_context": formatted_context
        }

memory_retriever = MemoryRetriever()

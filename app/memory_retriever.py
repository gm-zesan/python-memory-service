import re
import logging
from typing import Dict, Any, List, Optional
from .neo4j_client import neo4j_client
from .models import MemorySearchResultItem

logger = logging.getLogger(__name__)

class MemoryRetriever:
    @staticmethod
    def _matches_keyword(kw: str, query_lower: str, query_tokens: set) -> bool:
        kw = kw.lower()
        if len(kw) <= 2:
            return kw in query_tokens
        return kw in query_lower

    def compute_relevance(self, memory_item: Dict[str, Any], query: str) -> float:
        """
        Computes generic semantic relevance score (0.0 to 1.0) between query and memory item.
        """
        if not query or not query.strip():
            return 0.50

        q = query.lower()
        query_tokens = set(re.findall(r'\b\w+\b', q))
        
        category = str(memory_item.get("category", "")).lower()
        obj = str(memory_item.get("object", "")).lower()

        # Exact token match on category or object
        if obj in query_tokens or category in query_tokens:
            return 1.0

        # Substring match
        if obj and obj in q:
            return 0.90
        if category and category in q:
            return 0.90

        # Base relevance
        return 0.50 if memory_item.get("status") == "current" else 0.30

    def search_memories(
        self,
        workspace_id: int,
        customer_id: str,
        query: str = "",
        limit: int = 5,
        min_relevance: float = 0.40
    ) -> Dict[str, Any]:
        raw_memories = neo4j_client.search_customer_memories(
            workspace_id=workspace_id,
            customer_id=customer_id,
            limit=limit * 2
        )

        scored_items = []
        for m in raw_memories:
            score = self.compute_relevance(m, query)
            if score >= min_relevance:
                scored_items.append((score, m))

        # Sort by relevance descending, then current over past
        scored_items.sort(key=lambda x: (x[0], 1 if x[1].get("status") == "current" else 0), reverse=True)
        top_items = scored_items[:limit]

        formatted_lines = []
        items: List[MemorySearchResultItem] = []

        for score, m in top_items:
            rel = m.get("relation")
            cat = m.get("category", "")
            obj = m.get("object", "")
            status = m.get("status", "current")
            status_tag = f" ({status})" if status == "past" else ""

            if rel == "HAS_PREFERENCE":
                formatted_lines.append(f"- Preferred {cat}: {obj}{status_tag}")
            elif rel == "INTERESTED_IN":
                formatted_lines.append(f"- Showed Interest in {cat}: {obj}")
            elif rel == "REPORTED_ISSUE":
                formatted_lines.append(f"- Previous Issue ({cat}): {obj}")
            else:
                formatted_lines.append(f"- {cat}: {obj}{status_tag}")

            items.append(MemorySearchResultItem(
                type=m.get("type", "preference"),
                subject="Customer",
                relation=rel,
                object=str(obj),
                attributes=m,
                status=status,
                confidence=round(score, 2)
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

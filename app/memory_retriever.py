import re
import logging
from typing import Dict, Any, List, Optional
from .neo4j_client import neo4j_client
from .models import MemorySearchResultItem

logger = logging.getLogger(__name__)

# Keyword sets for intent & semantic domain mapping
DOMAIN_KEYWORDS = {
    "payment": {
        "payment", "pay", "paid", "bkash", "বিকাশ", "nagad", "নগদ", "rocket", "রকেট", 
        "card", "visa", "mastercard", "কার্ড", "পেমেন্ট", "টাকা", "bill", "billing", 
        "cod", "cash", "ক্যাশ", "checkout", "পেমেন্ট মেথড", "payment method"
    },
    "size": {
        "size", "সাইজ", "মাপ", "ফিটিং", "fitting", "xl", "xxl", "l", "m", "s", 
        "panjabi", "পাঞ্জাবি", "shirt", "শার্ট", "dress", "বড়", "ছোট", "tight", "loose"
    },
    "color": {
        "color", "colour", "রং", "কালার", "black", "কালো", "white", "সাদা", "blue", 
        "নীল", "navy", "নেভি", "red", "লাল", "maroon", "মেরুন", "green", "সবুজ"
    },
    "delivery": {
        "delivery", "ডেলিভারি", "deliver", "ship", "shipping", "courier", "কুরিয়ার", 
        "parcel", "পার্সেল", "সন্ধ্যা", "evening", "after", "পর", "office", "বাসা", "address", "ঠিকানা"
    },
    "order": {
        "order", "অর্ডার", "ord", "parcel", "পার্সেল", "status", "ট্র্যাকিং", "track", 
        "tracking", "কবে পাব", "কখন পাব", "আগের", "previous", "history"
    },
    "issue": {
        "issue", "problem", "সমস্যা", "complaint", "অভিযোগ", "damaged", "ভাঙ্গা", "নষ্ট", 
        "defective", "missing", "হারিয়ে", "wrong", "ভুল", "delay", "দেরি", "refund", "রিফান্ড"
    }
}

ORDERING_INTENT_KEYWORDS = {
    "order", "অর্ডার", "কিনতে চাই", "buy", "purchase", "need", "নিতে চাই", "lagbe", "লাগবে", "order korbo"
}

PROFILE_INQUIRY_KEYWORDS = {
    "about me", "my info", "আমার তথ্য", "আমার প্রেফারেন্স", "remember", "মনে আছে", "who am i", "আমার ডিটেইলস",
    "preference", "preferences", "details", "প্রেফারেন্স", "তথ্য"
}

class MemoryRetriever:
    @staticmethod
    def _matches_keyword(kw: str, query_lower: str, query_tokens: set) -> bool:
        kw = kw.lower()
        if len(kw) <= 2:
            return kw in query_tokens
        return kw in query_lower

    def compute_relevance(self, memory_item: Dict[str, Any], query: str) -> float:
        """
        Computes semantic relevance score (0.0 to 1.0) between query and memory item.
        """
        if not query or not query.strip():
            return 0.50

        q = query.lower()
        query_tokens = set(re.findall(r'\b\w+\b', q))
        rel = memory_item.get("relation", "")
        obj = str(memory_item.get("object", "")).lower()

        # 1. Customer asking directly about their profile / preferences
        for p_kw in PROFILE_INQUIRY_KEYWORDS:
            if self._matches_keyword(p_kw, q, query_tokens):
                return 1.0 if memory_item.get("status") == "current" else 0.70

        # 2. Exact value mentioned in query (e.g. "bKash", "XL", "1042")
        if obj:
            if len(obj) <= 2:
                if obj in query_tokens:
                    return 1.0
            elif obj in q:
                return 1.0

        # 3. Specific Domain Keyword Match
        domain = None
        if rel == "PREFERS":
            domain = "payment"
        elif rel == "PREFERS_SIZE":
            domain = "size"
        elif rel == "PREFERS_COLOR":
            domain = "color"
        elif rel == "PREFERS_DELIVERY":
            domain = "delivery"
        elif rel == "DISCUSSED":
            domain = "order"
        elif rel == "REPORTED":
            domain = "issue"
        elif rel == "INTERESTED_IN":
            domain = "order"

        if domain and domain in DOMAIN_KEYWORDS:
            keywords = DOMAIN_KEYWORDS[domain]
            if any(self._matches_keyword(kw, q, query_tokens) for kw in keywords):
                # Strong domain match
                return 0.95 if memory_item.get("status") == "current" else 0.65

        # 4. Active Ordering Intent: inject sizing, color, and payment preferences
        if any(self._matches_keyword(okw, q, query_tokens) for okw in ORDERING_INTENT_KEYWORDS):
            if rel in ("PREFERS_SIZE", "PREFERS_COLOR", "PREFERS"):
                return 0.80 if memory_item.get("status") == "current" else 0.40
            if rel == "DISCUSSED":
                return 0.60

        # 5. Low relevance for general / unrelated queries
        return 0.15

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
            limit=limit * 2  # Retrieve broader pool for relevance filtering
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
            obj = m.get("object")
            status = m.get("status", "current")
            status_tag = f" ({status})" if status == "past" else ""

            if rel == "PREFERS":
                formatted_lines.append(f"- Preferred Payment: {obj}{status_tag}")
            elif rel == "PREFERS_SIZE":
                formatted_lines.append(f"- Preferred Size: {obj}{status_tag}")
            elif rel == "PREFERS_COLOR":
                formatted_lines.append(f"- Preferred Color: {obj}{status_tag}")
            elif rel == "PREFERS_DELIVERY":
                formatted_lines.append(f"- Delivery Preference: {obj}{status_tag}")
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

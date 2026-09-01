import re
import logging
from typing import List, Dict, Any, Optional
from .models import MessageItem

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
        Extracts preferences, discussed orders, and reported issues from conversation turns.
        """
        extracted = {
            "payment_preference": None,
            "size_preference": None,
            "discussed_orders": [],
            "reported_issues": [],
            "interested_products": [],
        }

        for msg in messages:
            # We primarily extract customer preferences and intents from INBOUND messages
            if msg.direction != 'inbound':
                continue

            text = self.sanitize_text(msg.body)
            lower_text = text.lower()

            # 1. Payment Preference
            for kw, (code, name) in PAYMENT_METHODS.items():
                if kw in lower_text:
                    extracted["payment_preference"] = {"code": code, "name": name}
                    break

            # 2. Size Preference
            for pat in SIZE_PATTERNS:
                m = pat.search(text)
                if m:
                    val = m.group(2) if len(m.groups()) >= 2 else m.group(1)
                    if val:
                        extracted["size_preference"] = val.upper()
                        break

            # 3. Discussed Orders
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

            # 4. Reported Issues
            for kw, (category, desc) in ISSUE_KEYWORDS.items():
                if kw in lower_text:
                    if not any(i["category"] == category for i in extracted["reported_issues"]):
                        extracted["reported_issues"].append({
                            "category": category,
                            "description": desc
                        })

        return extracted

memory_extractor = MemoryExtractor()

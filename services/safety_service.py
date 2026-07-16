import re


RESTRICTED_RESPONSE = (
    "Sorry, I cannot assist with this request because it falls under a restricted category."
)


_ACTION = r"(?:how\s+to|steps?\s+to|instructions?\s+to|help\s+me|teach\s+me|create|make|build|bypass|steal|hack)"
_RESTRICTED_PATTERNS = [
    rf"{_ACTION}.{{0,80}}(?:malware|ransomware|phishing|credential\s+theft|account\s+takeover)",
    rf"{_ACTION}.{{0,80}}(?:explosive|bomb|illegal\s+weapon|poison)",
    rf"{_ACTION}.{{0,80}}(?:buy|sell|obtain).{{0,40}}(?:illegal\s+drug|controlled\s+substance)",
    rf"{_ACTION}.{{0,80}}(?:sexual\s+content\s+involving\s+minors?|child\s+sexual)",
    rf"{_ACTION}.{{0,80}}(?:self[- ]harm|suicide)",
    rf"{_ACTION}.{{0,80}}(?:stalk|doxx|blackmail|extort)",
]


def is_restricted_request(text: str) -> bool:
    """Conservative local pre-check for explicit harmful instructions.

    This intentionally targets requests for instructions or facilitation, not
    ordinary educational, prevention, news, or recovery discussions.
    """
    normalized = " ".join(text.lower().split())[:5000]
    return any(re.search(pattern, normalized) for pattern in _RESTRICTED_PATTERNS)

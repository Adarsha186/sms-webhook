import hashlib
import hmac
from typing import Dict, Optional
from urllib.parse import parse_qs


def parse_form(raw: bytes) -> Dict[str, str]:
    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items()}


def verify_signature(raw: bytes, secret: str, signature: Optional[str]) -> bool:
    if signature is None:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    # Compare bytes: compare_digest raises on non-ASCII strings.
    return hmac.compare_digest(expected.encode(), signature.encode())

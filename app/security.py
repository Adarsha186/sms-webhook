import hashlib
import hmac
import re
from typing import Dict, Optional
from urllib.parse import parse_qs

MAX_BODY_BYTES = 16 * 1024
REQUIRED_FIELDS = ("MessageSid", "From", "To", "Body")
NON_EMPTY_FIELDS = ("MessageSid", "From", "To")

# Deliberately loose: the brief gives no format, and rejecting a signed message
# loses it. This only blocks values that can't be a stable identifier.
MESSAGE_SID = re.compile(r"[^\s\x00-\x1f\x7f]{1,255}")


class InvalidRequest(ValueError):
    """A rejected request. Messages must never repeat the caller's input."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def parse_form(raw: bytes) -> Dict[str, str]:
    try:
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True, errors="strict")
    except UnicodeDecodeError:
        raise InvalidRequest(400, "invalid_encoding", "The body is not valid UTF-8.")

    for field in REQUIRED_FIELDS:
        if len(parsed.get(field, [])) > 1:
            raise InvalidRequest(400, "repeated_field", f"{field} appears more than once.")

    form = {field: parsed.get(field, [None])[0] for field in REQUIRED_FIELDS}
    for field in REQUIRED_FIELDS:
        if form[field] is None or (field in NON_EMPTY_FIELDS and not form[field]):
            raise InvalidRequest(400, "missing_field", f"{field} is required.")
    return form


def validate_message_sid(message_sid: str) -> None:
    """Runs after the signature check, so it can't replace a required 403 or 404."""
    if not MESSAGE_SID.fullmatch(message_sid):
        raise InvalidRequest(
            400,
            "invalid_message_sid",
            "MessageSid must be 1 to 255 characters, with no spaces or control characters.",
        )


def verify_signature(raw: bytes, secret: str, signature: Optional[str]) -> bool:
    if signature is None:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    # Compare bytes: compare_digest raises on non-ASCII strings.
    return hmac.compare_digest(expected.encode(), signature.encode())

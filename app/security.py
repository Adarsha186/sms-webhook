import hashlib
import hmac
import re
from typing import Dict, Optional
from urllib.parse import parse_qs

MAX_BODY_BYTES = 16 * 1024
REQUIRED_FIELDS = ("MessageSid", "From", "To", "Body")
NON_EMPTY_FIELDS = ("MessageSid", "From", "To")

MESSAGE_SID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Deliberately loose: an unknown To must reach the 404 and an unmatched From is
# still stored, so these are not phone-format checks.
NUMBER = re.compile(r"[^\x00-\x1f\x7f]{1,32}")


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

    if not MESSAGE_SID.fullmatch(form["MessageSid"]):
        raise InvalidRequest(
            400,
            "invalid_message_sid",
            "MessageSid must be 1 to 64 letters, digits, dashes or underscores.",
        )
    if not NUMBER.fullmatch(form["From"]):
        raise InvalidRequest(400, "invalid_from", "From is not a valid sender.")
    if not NUMBER.fullmatch(form["To"]):
        raise InvalidRequest(400, "invalid_to", "To is not a valid number.")
    return form


def verify_signature(raw: bytes, secret: str, signature: Optional[str]) -> bool:
    if signature is None:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    # Compare bytes: compare_digest raises on non-ASCII strings.
    return hmac.compare_digest(expected.encode(), signature.encode())

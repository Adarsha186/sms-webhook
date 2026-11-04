"""Named bad inputs for the webhook.

Every case is correctly signed with acme's secret unless `signature` says
otherwise, so a rejection can only come from the defect the case describes.
"""
import hashlib
import hmac
from dataclasses import dataclass
from typing import Optional, Union
from urllib.parse import urlencode

ACME_SECRET = "acme-secret"
BAKER_SECRET = "baker-secret"
ACME_NUMBER = "+15550000001"
BAKER_NUMBER = "+15550000002"
SENDER = "+15551110001"

SIGN_WITH_ACME = "sign-with-acme"


def form(**overrides) -> bytes:
    """Build a valid body. Override a field, or pass None to remove it."""
    fields = {"MessageSid": "SM1000", "From": SENDER, "To": ACME_NUMBER, "Body": "Hello"}
    fields.update(overrides)
    return urlencode({k: v for k, v in fields.items() if v is not None}).encode()


def sign(raw: bytes, secret: str = ACME_SECRET) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class FailureCase:
    id: str
    body: bytes
    status: int
    code: str
    signature: Union[str, bytes, None] = SIGN_WITH_ACME


MISSING_FIELDS = [
    FailureCase("missing-message-sid", form(MessageSid=None), 400, "missing_field"),
    FailureCase("missing-from", form(From=None), 400, "missing_field"),
    FailureCase("missing-to", form(To=None), 400, "missing_field"),
    FailureCase("missing-body", form(Body=None), 400, "missing_field"),
    FailureCase("empty-request", b"", 400, "missing_field"),
    FailureCase("json-instead-of-form", b'{"MessageSid": "SM1"}', 400, "missing_field"),
    FailureCase("empty-message-sid", form(MessageSid=""), 400, "missing_field"),
    FailureCase("empty-from", form(From=""), 400, "missing_field"),
    FailureCase("empty-to", form(To=""), 400, "missing_field"),
    FailureCase("missing-field-unsigned", form(Body=None), 400, "missing_field", None),
]

INVALID_MESSAGE_SIDS = [
    FailureCase("sid-only-spaces", form(MessageSid="   "), 400, "invalid_message_sid"),
    FailureCase("sid-inner-space", form(MessageSid="SM 1"), 400, "invalid_message_sid"),
    FailureCase("sid-trailing-space", form(MessageSid="SM1 "), 400, "invalid_message_sid"),
    FailureCase("sid-trailing-newline", form(MessageSid="SM1\n"), 400, "invalid_message_sid"),
    FailureCase("sid-nul-byte", form(MessageSid="SM\x001"), 400, "invalid_message_sid"),
    FailureCase(
        "sid-undecodable",
        form().replace(b"MessageSid=SM1000", b"MessageSid=SM%FF1"),
        400,
        "invalid_message_sid",
    ),
    FailureCase("sid-too-long", form(MessageSid="S" * 256), 400, "invalid_message_sid"),
    FailureCase(
        "sid-sql-text",
        form(MessageSid="SM1'; DROP TABLE messages;--"),
        400,
        "invalid_message_sid",
    ),
]

MALFORMED_BODIES = [
    FailureCase("repeated-to", form() + b"&To=%2B15550000002", 400, "repeated_field"),
    FailureCase("repeated-sid", form() + b"&MessageSid=SM2", 400, "repeated_field"),
    FailureCase("undecodable-bytes-with-no-fields", b"\xff\xfe", 400, "missing_field"),
]

UNKNOWN_NUMBERS = [
    FailureCase("unknown-to", form(To="+15559999999"), 404, "unknown_to"),
    FailureCase("to-is-not-a-number", form(To="not-a-number"), 404, "unknown_to"),
    FailureCase("unknown-to-unsigned", form(To="+15559999999"), 404, "unknown_to", None),
    FailureCase("to-very-long", form(To="+1" * 20), 404, "unknown_to"),
    FailureCase("to-control-character", form(To="+1555\n"), 404, "unknown_to"),
]

BAD_SIGNATURES = [
    FailureCase("signature-missing", form(), 403, "invalid_signature", None),
    FailureCase("signature-empty", form(), 403, "invalid_signature", ""),
    FailureCase("signature-wrong", form(), 403, "invalid_signature", "0" * 64),
    FailureCase("signature-too-short", form(), 403, "invalid_signature", sign(form())[:32]),
    FailureCase("signature-not-hex", form(), 403, "invalid_signature", "z" * 64),
    FailureCase("signature-uppercase", form(), 403, "invalid_signature", sign(form()).upper()),
    FailureCase("signature-non-ascii", form(), 403, "invalid_signature", b"\xff\xfe"),
    FailureCase(
        "signature-other-tenant",
        form(),
        403,
        "invalid_signature",
        sign(form(), BAKER_SECRET),
    ),
    FailureCase(
        "signature-for-other-body",
        form(Body="Tampered"),
        403,
        "invalid_signature",
        sign(form()),
    ),
    FailureCase(
        "large-body-unsigned", form(Body="x" * 20000), 403, "invalid_signature", None
    ),
    FailureCase(
        "undecodable-body-unsigned",
        form().replace(b"Body=Hello", b"Body=caf%E9"),
        403,
        "invalid_signature",
        None,
    ),
    FailureCase("bad-sid-unsigned", form(MessageSid="SM 1"), 403, "invalid_signature", None),
    FailureCase("forged-stop-unsigned", form(Body="STOP"), 403, "invalid_signature", None),
    FailureCase("forged-stop-wrong", form(Body="STOP"), 403, "invalid_signature", "0" * 64),
    FailureCase(
        "forged-stop-other-tenant",
        form(Body="STOP"),
        403,
        "invalid_signature",
        sign(form(Body="STOP"), BAKER_SECRET),
    ),
]

ALL_FAILURES = (
    MISSING_FIELDS
    + INVALID_MESSAGE_SIDS
    + MALFORMED_BODIES
    + UNKNOWN_NUMBERS
    + BAD_SIGNATURES
)

# Unusual but valid: these must still be accepted.
ACCEPTED_BODIES = {
    "sid-at-max-length": form(MessageSid="S" * 255),
    "sid-with-dash-and-underscore": form(MessageSid="SM_a-1"),
    "sid-with-dot": form(MessageSid="SM.0001"),
    "sid-with-colon": form(MessageSid="msg:abc"),
    "sid-non-ascii": form(MessageSid="SM\u00e91"),
    "very-long-sender": form(From="+1" * 20),
    "sender-with-control-character": form(From="+1555\x00"),
    "empty-message-body": form(Body=""),
    "very-long-message-body": form(Body="x" * 20000),
    "percent-encoded-undecodable-body": form().replace(b"Body=Hello", b"Body=caf%E9"),
    "raw-undecodable-body": form().replace(b"Body=Hello", b"Body=caf\xe9"),
    "short-code-sender": form(From="12345"),
    "unknown-sender-text": form(From="unknown"),
    "non-ascii-message-body": form(Body="Héllo ✓"),
    "extra-field-is-ignored": form() + b"&NumMedia=0",
    "percent-20-for-space": b"MessageSid=SM1000&From=%2B15551110001&To=%2B15550000001&Body=a%20b",
    "lowercase-percent-encoding": b"MessageSid=SM1000&From=%2b15551110001&To=%2b15550000001&Body=Hi",
}

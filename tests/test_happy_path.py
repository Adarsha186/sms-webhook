import hashlib
import hmac
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.classifier import KeywordClassifier
from app.main import create_app

FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
BRIEF_BODY = (
    b"MessageSid=SM0001&From=%2B15551110001&To=%2B15550000001"
    b"&Body=When+is+my+hearing%3F"
)
BRIEF_SIGNATURE = "33599426679aaabb3e29c4291341f4c6e274c95f4333e604967a1d295e8e1054"


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "test.db"), KeywordClassifier())
    return TestClient(app)


def post_signed(client, secret, sid, sender, to, body):
    raw = urlencode(
        {"MessageSid": sid, "From": sender, "To": to, "Body": body}
    ).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/sms",
        content=raw,
        headers={**FORM_HEADERS, "X-Signature": signature},
    )


def test_brief_example_is_stored_and_listed(client):
    response = client.post(
        "/webhooks/sms",
        content=BRIEF_BODY,
        headers={**FORM_HEADERS, "X-Signature": BRIEF_SIGNATURE},
    )

    assert response.status_code == 200
    assert client.get("/tenants/acme-law/messages").json() == [
        {
            "message_sid": "SM0001",
            "claimant_id": "C-100",
            "body": "When is my hearing?",
            "category": "status_question",
            "needs_review": False,
            "dnc": False,
        }
    ]


def test_wrong_signature_is_rejected_without_storing(client):
    response = client.post(
        "/webhooks/sms",
        content=BRIEF_BODY,
        headers={**FORM_HEADERS, "X-Signature": "0" * 64},
    )

    assert response.status_code == 403
    assert client.get("/tenants/acme-law/messages").json() == []


def test_unmatched_sender_is_stored_with_no_claimant(client):
    response = post_signed(
        client, "acme-secret", "SM0002", "+15559999999", "+15550000001", "Hello"
    )

    assert response.status_code == 200
    message = client.get("/tenants/acme-law/messages").json()[0]
    assert message["claimant_id"] is None
    assert message["category"] == "other"


def test_known_tenant_with_no_messages_returns_empty_list(client):
    response = client.get("/tenants/baker-llp/messages")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "text, category",
    [
        ("When is my hearing?", "status_question"),
        ("What is the status of my case?", "status_question"),
        ("I have attached the document", "document_upload"),
        ("Can we schedule a call?", "schedule_call"),
        ("Thanks very much", "other"),
    ],
)
def test_keyword_classifier_picks_category(text, category):
    assert KeywordClassifier().classify(text) == category

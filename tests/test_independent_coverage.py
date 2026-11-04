"""Independent coverage check, derived from the brief, CLAUDE.md and the plan.

Each test here covers a behaviour the rest of the suite left unchecked, or only
checked with an assertion that would survive the protection being removed.
"""
import sqlite3
from contextlib import closing
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.classifier import CATEGORIES, KeywordClassifier
from app.db import connect
from app.main import create_app
from failure_data import (
    ACME_NUMBER,
    ACME_SECRET,
    BAKER_NUMBER,
    BAKER_SECRET,
    SENDER,
    FailureCase,
    form,
    sign,
)
from helpers import SpyClassifier, post, stored

UNMATCHED = "+15559999999"
SID_FIELD = b"MessageSid=SM1000"
BODY_FIELD = b"Body=Hello"


def with_raw_sid(raw_value: bytes) -> bytes:
    return form().replace(SID_FIELD, b"MessageSid=" + raw_value)


def with_raw_body(raw_value: bytes) -> bytes:
    return form().replace(BODY_FIELD, b"Body=" + raw_value)


def post_baker(client, **overrides):
    body = form(To=BAKER_NUMBER, **overrides)
    return post(client, body, sign(body, BAKER_SECRET))


def opted_out_ids(db_path):
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT id FROM claimants WHERE opted_out = 1 ORDER BY id"
        ).fetchall()
    return [row["id"] for row in rows]


def run_sql(db_path, statement):
    with closing(connect(db_path)) as conn:
        conn.execute(statement)
        conn.commit()


class AnswerByText:
    """Answers per message text, and records what it was asked."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def classify(self, text):
        self.calls.append(text)
        return self.answers[text]


class RaisingClassifier:
    def __init__(self, error):
        self.error = error
        self.calls = []

    def classify(self, text):
        self.calls.append(text)
        raise self.error


# Requirement 1: the signature covers the original bytes, so the same fields in
# different bytes are a different message.
REENCODED = b"MessageSid=SM1000&From=%2B15551110001&To=%2B15550000001&Body=a+b"
REORDERED = b"Body=Hello&To=%2B15550000001&From=%2B15551110001&MessageSid=SM1000"

SIGNATURE_BOUND_TO_BYTES = [
    FailureCase(
        "same-fields-different-encoding",
        REENCODED.replace(b"a+b", b"a%20b"),
        403,
        "invalid_signature",
        sign(REENCODED),
    ),
    FailureCase("same-fields-reordered", REORDERED, 403, "invalid_signature", sign(form())),
    FailureCase("trailing-ampersand", form() + b"&", 403, "invalid_signature", sign(form())),
    FailureCase(
        "valid-signature-with-suffix", form(), 403, "invalid_signature", sign(form()) + "00"
    ),
    FailureCase(
        "acme-signature-sent-to-baker",
        form(To=BAKER_NUMBER),
        403,
        "invalid_signature",
        sign(form(To=BAKER_NUMBER), ACME_SECRET),
    ),
]

# Approved change: MessageSid checks, including undecodable bytes, come after
# the signature. An unsigned request must learn nothing about its format.
SID_CHECKS_FOLLOW_SIGNATURE = [
    FailureCase(
        "undecodable-sid-unsigned", with_raw_sid(b"SM%FF1"), 403, "invalid_signature", None
    ),
    FailureCase(
        "undecodable-sid-wrong-signature",
        with_raw_sid(b"SM%FF1"),
        403,
        "invalid_signature",
        "0" * 64,
    ),
    FailureCase(
        "raw-undecodable-sid-unsigned", with_raw_sid(b"SM\xff1"), 403, "invalid_signature", None
    ),
    FailureCase(
        "too-long-sid-unsigned", form(MessageSid="S" * 256), 403, "invalid_signature", None
    ),
    FailureCase("control-sid-unsigned", form(MessageSid="SM\x001"), 403, "invalid_signature", None),
]

INVALID_SIDS = [
    FailureCase("raw-undecodable-sid", with_raw_sid(b"SM\xff1"), 400, "invalid_message_sid"),
    FailureCase("plus-decodes-to-space", with_raw_sid(b"SM+1"), 400, "invalid_message_sid"),
    FailureCase("tab", form(MessageSid="SM\t1"), 400, "invalid_message_sid"),
    FailureCase("carriage-return", form(MessageSid="SM\r1"), 400, "invalid_message_sid"),
    FailureCase("unit-separator", form(MessageSid="SM\x1f1"), 400, "invalid_message_sid"),
    FailureCase("delete-character", form(MessageSid="SM\x7f1"), 400, "invalid_message_sid"),
    FailureCase("c1-control", form(MessageSid="SM\x851"), 400, "invalid_message_sid"),
    FailureCase("no-break-space", form(MessageSid="SM 1"), 400, "invalid_message_sid"),
    FailureCase("em-space", form(MessageSid="SM 1"), 400, "invalid_message_sid"),
    FailureCase("too-many-wide-characters", form(MessageSid="é" * 256), 400, "invalid_message_sid"),
    FailureCase(
        "signed-stop-with-bad-sid",
        form(MessageSid="SM 1", Body="STOP"),
        400,
        "invalid_message_sid",
    ),
    FailureCase(
        "signed-stop-with-undecodable-sid",
        form(Body="STOP").replace(SID_FIELD, b"MessageSid=SM%FF1"),
        400,
        "invalid_message_sid",
    ),
]

REPEATED_FIELDS = [
    FailureCase("repeated-from", form() + b"&From=%2B15551110002", 400, "repeated_field"),
    FailureCase("repeated-body", form() + b"&Body=STOP", 400, "repeated_field"),
    FailureCase("repeated-field-unsigned", form() + b"&MessageSid=SM2", 400, "repeated_field", None),
]

UNDECODABLE_TO = [
    FailureCase("undecodable-to", form().replace(b"To=%2B15550000001", b"To=%FF"), 404, "unknown_to"),
    FailureCase(
        "undecodable-to-unsigned",
        form().replace(b"To=%2B15550000001", b"To=%FF"),
        404,
        "unknown_to",
        None,
    ),
]

REJECTIONS = (
    SIGNATURE_BOUND_TO_BYTES
    + SID_CHECKS_FOLLOW_SIGNATURE
    + INVALID_SIDS
    + REPEATED_FIELDS
    + UNDECODABLE_TO
)


@pytest.mark.parametrize("case", REJECTIONS, ids=lambda case: case.id)
def test_rejection_has_no_side_effects(client, spy, db_path, case):
    response = post(client, case.body, case.signature)

    assert response.status_code == case.status
    assert response.json()["error"]["code"] == case.code
    assert stored(client, "acme-law") == []
    assert stored(client, "baker-llp") == []
    assert spy.calls == []
    assert opted_out_ids(db_path) == []


@pytest.mark.parametrize(
    "sid",
    ["é" * 255, "SM�1", "S"],
    ids=["255-wide-characters", "real-replacement-character", "one-character"],
)
def test_message_sid_limits_count_characters_and_only_reject_the_named_defects(client, sid):
    assert post(client, form(MessageSid=sid)).status_code == 200
    assert stored(client)[0]["message_sid"] == sid


def test_message_sid_is_case_sensitive(client):
    post(client, form(MessageSid="SMabc"))
    post(client, form(MessageSid="SMABC"))

    assert [m["message_sid"] for m in stored(client)] == ["SMabc", "SMABC"]


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/json", None],
    ids=["text", "json", "absent"],
)
def test_content_type_does_not_decide_acceptance(client, content_type):
    body = form()
    headers = {"X-Signature": sign(body)}
    if content_type:
        headers["Content-Type"] = content_type

    response = client.post("/webhooks/sms", content=body, headers=headers)

    assert response.status_code == 200
    assert len(stored(client)) == 1


def test_signed_json_body_with_json_content_type_is_a_missing_field(client, spy):
    body = b'{"MessageSid": "SM1", "From": "a", "To": "b", "Body": "c"}'

    response = client.post(
        "/webhooks/sms",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": sign(body)},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_field"
    assert stored(client) == []
    assert spy.calls == []


@pytest.mark.parametrize(
    "raw, text",
    [
        (b"a%20b", "a b"),
        (b"a+b", "a b"),
        (b"a%2Bb", "a+b"),
        (b"a%26To%3Dx", "a&To=x"),
        (b"H%C3%A9llo+%E2%9C%93", "Héllo ✓"),
        (b"a%00b", "a\x00b"),
        (b"a%ED%A0%80b", "a���b"),
    ],
    ids=["percent-20", "plus", "encoded-plus", "encoded-separators", "utf-8", "nul", "surrogate"],
)
def test_body_is_decoded_and_stored_as_the_text_sent(client, spy, raw, text):
    response = post(client, with_raw_body(raw))

    assert response.status_code == 200
    assert stored(client)[0]["body"] == text
    assert spy.calls == [text]


def test_lowercase_percent_encoding_still_finds_tenant_and_claimant(client):
    body = b"MessageSid=SM1&From=%2b15551110001&To=%2b15550000001&Body=Hi"

    assert post(client, body).status_code == 200
    assert stored(client)[0]["claimant_id"] == "C-100"


def test_correctly_signed_body_in_any_field_order_is_accepted(client):
    assert post(client, REORDERED).status_code == 200
    message = stored(client)[0]
    assert message["message_sid"] == "SM1000"
    assert message["claimant_id"] == "C-100"


@pytest.mark.parametrize(
    "body",
    [
        form().replace(b"From=%2B15551110001", b"From=%FF"),
        form().replace(b"From=%2B15551110001", b"From=\xff"),
    ],
    ids=["percent-encoded", "raw"],
)
def test_undecodable_from_is_stored_with_no_claimant(client, body):
    assert post(client, body).status_code == 200
    assert stored(client)[0]["claimant_id"] is None


def test_undecodable_unknown_field_is_ignored(client):
    assert post(client, form() + b"&NumMedia=%FF").status_code == 200
    assert len(stored(client)) == 1


def test_there_is_no_body_size_limit(client, spy):
    text = "x" * 2_000_000

    response = post(client, form(Body=text))

    assert response.status_code == 200
    assert stored(client)[0]["body"] == text
    assert spy.calls == [text]


@pytest.mark.parametrize(
    "body, signature, status",
    [
        (form(MessageSid="SMmarker 1", From="+15557654321"), "sign", 400),
        (form(MessageSid="SMmarker", From="+15557654321", Body=None), "sign", 400),
        (form(MessageSid="SMmarker", From="+15557654321") + b"&To=marker", "sign", 400),
        (form(MessageSid="SMmarker", From="+15557654321"), None, 403),
    ],
    ids=["bad-sid", "missing-field", "repeated-field", "bad-signature"],
)
def test_no_rejection_repeats_the_input(client, body, signature, status):
    response = post(client, body, sign(body) if signature else None)

    assert response.status_code == status
    assert "marker" not in response.text
    assert "7654321" not in response.text


def test_unknown_tenant_error_does_not_repeat_the_path(client):
    response = client.get("/tenants/marker-firm/messages")

    assert response.status_code == 404
    assert "marker" not in response.text


def test_nothing_sensitive_reaches_logs_or_output(db_path, caplog, capfd):
    text = "my private message"
    client = TestClient(
        create_app(db_path, RaisingClassifier(RuntimeError(f"failed on {text}")))
    )

    with caplog.at_level("DEBUG"):
        post(client, form(MessageSid="SM1", Body=text))
        post(client, form(MessageSid="SM2", Body="STOP"))
        post(client, form(MessageSid="SM3", Body=text), "0" * 64)
        post(client, form(MessageSid="SM 4", Body=text))

    written = caplog.text + "".join(capfd.readouterr())
    for secret in (text, SENDER, SENDER[1:], ACME_NUMBER, ACME_NUMBER[1:], ACME_SECRET):
        assert secret not in written


# Requirement 2: stored once per tenant, and the model is not called again.


def test_retry_after_a_classifier_error_does_not_call_it_again(db_path):
    classifier = RaisingClassifier(RuntimeError("model unavailable"))
    client = TestClient(create_app(db_path, classifier))

    post(client, form())
    response = post(client, form())

    assert response.status_code == 200
    assert classifier.calls == ["Hello"]
    assert len(stored(client)) == 1
    assert stored(client)[0]["needs_review"] is True


def test_retry_after_a_bad_answer_keeps_the_review_flag(db_path):
    classifier = AnswerByText({"Hello": "banana"})
    client = TestClient(create_app(db_path, classifier))

    post(client, form())
    post(client, form())

    assert classifier.calls == ["Hello"]
    assert stored(client)[0]["needs_review"] is True


def test_repeat_sid_with_a_stop_body_keeps_the_first_message(client, spy, db_path):
    post(client, form(Body="Hello"))

    response = post(client, form(Body="STOP"))

    assert response.status_code == 200
    assert opted_out_ids(db_path) == []
    assert [(m["body"], m["category"], m["dnc"]) for m in stored(client)] == [
        ("Hello", "other", False)
    ]


def test_repeat_sid_after_a_stop_does_not_call_the_classifier(client, spy):
    post(client, form(Body="STOP"))

    response = post(client, form(Body="Hello"))

    assert response.status_code == 200
    assert spy.calls == []
    assert [(m["body"], m["category"]) for m in stored(client)] == [("STOP", None)]


def test_repeat_after_a_restart_is_still_a_repeat(db_path, spy):
    post(TestClient(create_app(db_path, spy)), form())
    restarted = TestClient(create_app(db_path, spy))

    assert post(restarted, form()).status_code == 200
    assert len(stored(restarted)) == 1
    assert len(spy.calls) == 1


class ProbeClassifier:
    """Looks at the database from inside classify, as a slow model call would."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.row = None
        self.error = None

    def classify(self, text):
        try:
            with closing(connect(self.db_path)) as conn:
                conn.execute("PRAGMA busy_timeout = 0")
                self.row = conn.execute(
                    "SELECT category, needs_review FROM messages WHERE message_sid = 'SM1000'"
                ).fetchone()
                conn.execute("UPDATE claimants SET opted_out = 0 WHERE id = 'C-101'")
                conn.commit()
        except sqlite3.Error as error:
            self.error = error
        return "status_question"


def test_row_is_committed_for_review_and_unlocked_during_the_classifier_call(db_path):
    probe = ProbeClassifier(db_path)
    client = TestClient(create_app(db_path, probe))

    post(client, form())

    assert probe.error is None
    assert probe.row is not None
    assert (probe.row["category"], probe.row["needs_review"]) == ("other", 1)
    assert stored(client)[0]["category"] == "status_question"
    assert stored(client)[0]["needs_review"] is False


# Requirements 2, 3 and 5: the row updated after classifying must be this
# tenant's, because the same MessageSid can exist in both tenants.


def test_classifying_one_tenant_leaves_the_same_sid_in_the_other_alone(db_path):
    classifier = AnswerByText({"For acme": "status_question", "For baker": "document_upload"})
    client = TestClient(create_app(db_path, classifier))

    post(client, form(Body="For acme"))
    post_baker(client, Body="For baker")

    assert stored(client, "acme-law")[0]["category"] == "status_question"
    assert stored(client, "baker-llp")[0]["category"] == "document_upload"


def test_valid_answer_in_one_tenant_keeps_the_others_review_flag(db_path):
    classifier = AnswerByText({"For acme": "banana", "For baker": "schedule_call"})
    client = TestClient(create_app(db_path, classifier))

    post(client, form(Body="For acme"))
    post_baker(client, Body="For baker")

    acme = stored(client, "acme-law")[0]
    assert (acme["category"], acme["needs_review"]) == ("other", True)


# Requirement 4: STOP.


@pytest.mark.parametrize("text", ["sToPaLl", "uNsUbScRiBe", " \r\n StopAll \t "])
def test_stop_keywords_match_in_mixed_case(client, spy, db_path, text):
    post(client, form(Body=text))

    assert spy.calls == []
    assert opted_out_ids(db_path) == ["C-100"]
    assert stored(client)[0]["body"] == text


def test_stop_from_a_number_known_only_to_the_other_tenant(client, spy, db_path):
    response = post(client, form(From="+15551110003", Body="STOP"))

    assert response.status_code == 200
    assert spy.calls == []
    assert opted_out_ids(db_path) == []
    message = stored(client)[0]
    assert message["claimant_id"] is None
    assert message["dnc"] is True


def test_new_stop_from_an_opted_out_claimant_is_stored_without_classifying(
    client, spy, db_path
):
    post(client, form(MessageSid="SM1", Body="STOP"))
    post(client, form(MessageSid="SM2", Body="unsubscribe"))

    assert spy.calls == []
    assert opted_out_ids(db_path) == ["C-100"]
    assert [m["category"] for m in stored(client)] == [None, None]


def test_failed_message_insert_does_not_leave_the_opt_out_set(client, db_path):
    run_sql(
        db_path,
        "CREATE TRIGGER block_message BEFORE INSERT ON messages "
        "BEGIN SELECT RAISE(ABORT, 'insert failed'); END",
    )
    failing_client = TestClient(client.app, raise_server_exceptions=False)

    assert post(failing_client, form(Body="STOP")).status_code == 500
    assert opted_out_ids(db_path) == []

    run_sql(db_path, "DROP TRIGGER block_message")

    assert post(client, form(Body="STOP")).status_code == 200
    assert opted_out_ids(db_path) == ["C-100"]


def test_stop_followed_by_undecodable_bytes_is_not_a_stop(client, spy, db_path):
    post(client, with_raw_body(b"STOP%FF"))

    assert spy.calls == ["STOP�"]
    assert opted_out_ids(db_path) == []
    assert stored(client)[0]["category"] == "other"


def test_opt_out_survives_a_restart_and_seeding_adds_no_rows(db_path, spy):
    post(TestClient(create_app(db_path, spy)), form(Body="STOP"))

    restarted = TestClient(create_app(db_path, spy))

    assert opted_out_ids(db_path) == ["C-100"]
    assert stored(restarted)[0]["dnc"] is True
    with closing(connect(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM claimants").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0] == 2


# Approved change: dnc on an unmatched number is true on the STOP alone.


def test_dnc_from_an_unmatched_number_is_only_on_the_stop(client):
    post(client, form(MessageSid="SM1", From=UNMATCHED, Body="Hello"))
    post(client, form(MessageSid="SM2", From=UNMATCHED, Body="STOP"))
    post(client, form(MessageSid="SM3", From=UNMATCHED, Body="Hello again"))

    assert [m["dnc"] for m in stored(client)] == [False, True, False]


def test_dnc_does_not_depend_on_the_classifier_outcome(db_path):
    client = TestClient(create_app(db_path, SpyClassifier(answer="banana")))

    post(client, form(MessageSid="SM1"))
    post(client, form(MessageSid="SM2", Body="STOP"))

    first = stored(client)[0]
    assert (first["needs_review"], first["dnc"]) == (True, True)


# Requirement 5: classification.


@pytest.mark.parametrize(
    "text",
    ["  Hello  ", "Hello\n", "\tMiXeD Case "],
    ids=["spaces", "newline", "tab-and-case"],
)
def test_non_stop_body_is_stored_and_classified_exactly_as_received(client, spy, text):
    post(client, form(Body=text))

    assert stored(client)[0]["body"] == text
    assert spy.calls == [text]


@pytest.mark.parametrize(
    "error",
    [ValueError("bad"), TimeoutError("slow"), KeyError("missing"), MemoryError()],
    ids=lambda error: type(error).__name__,
)
def test_any_classifier_exception_stores_other_for_review(db_path, error):
    client = TestClient(create_app(db_path, RaisingClassifier(error)))

    response = post(client, form())

    assert response.status_code == 200
    message = stored(client)[0]
    assert (message["category"], message["needs_review"]) == ("other", True)


@pytest.mark.parametrize(
    "answer",
    [b"other", True, "OTHER", "other\n", ("other",), "status_question,other"],
    ids=repr,
)
def test_near_miss_answers_store_other_for_review(db_path, answer):
    client = TestClient(create_app(db_path, SpyClassifier(answer=answer)))

    assert post(client, form()).status_code == 200
    message = stored(client)[0]
    assert (message["category"], message["needs_review"]) == ("other", True)


def test_default_classifier_answers_other_for_an_empty_message():
    assert KeywordClassifier().classify("") == "other"


@pytest.mark.parametrize(
    "text",
    ["status of the document, and schedule a call", "�", "x" * 10000],
    ids=["several-topics", "replacement-character", "long"],
)
def test_default_classifier_gives_one_repeatable_category(text):
    answer = KeywordClassifier().classify(text)

    assert answer in CATEGORIES
    assert KeywordClassifier().classify(text) == answer


# Requirement 6: GET.


def test_messages_are_listed_in_insert_order(client):
    for sid in ("SM9", "SM1", "SM5"):
        post(client, form(MessageSid=sid))

    assert [m["message_sid"] for m in stored(client)] == ["SM9", "SM1", "SM5"]


def test_each_tenant_lists_only_its_own_messages(client):
    post(client, form(MessageSid="SM-acme", Body="For acme"))
    post_baker(client, MessageSid="SM-baker", Body="For baker")

    assert [(m["message_sid"], m["body"], m["claimant_id"]) for m in stored(client)] == [
        ("SM-acme", "For acme", "C-100")
    ]
    assert [
        (m["message_sid"], m["body"], m["claimant_id"]) for m in stored(client, "baker-llp")
    ] == [("SM-baker", "For baker", "C-200")]


@pytest.mark.parametrize(
    "tenant",
    ["ACME-LAW", "acme-law ", ACME_NUMBER, "acme-law' OR '1'='1", "%"],
    ids=["uppercase", "trailing-space", "phone-number", "sql-text", "wildcard"],
)
def test_only_the_exact_tenant_slug_is_known(client, tenant):
    post(client, form())

    response = client.get(f"/tenants/{quote(tenant, safe='')}/messages")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant"

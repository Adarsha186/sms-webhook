import threading
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import ingest
from app.db import connect
from app.main import create_app
from failure_data import (
    ACCEPTED_BODIES,
    ALL_FAILURES,
    BAKER_NUMBER,
    BAKER_SECRET,
    SIGN_WITH_ACME,
    FailureCase,
    form,
    sign,
)
from helpers import SpyClassifier, post, stored


@pytest.mark.parametrize("case", ALL_FAILURES, ids=lambda case: case.id)
def test_bad_input_is_rejected_without_side_effects(
    client, spy, db_path, case: FailureCase
):
    response = post(client, case.body, case.signature)

    assert response.status_code == case.status
    assert response.json()["error"]["code"] == case.code
    assert response.json()["error"]["message"]
    assert stored(client, "acme-law") == []
    assert stored(client, "baker-llp") == []
    assert spy.calls == []
    with closing(connect(db_path)) as conn:
        assert conn.execute("SELECT id FROM claimants WHERE opted_out = 1").fetchall() == []


@pytest.mark.parametrize("name", ACCEPTED_BODIES)
def test_unusual_but_valid_input_is_accepted(client, spy, name):
    body = ACCEPTED_BODIES[name]

    response = post(client, body, SIGN_WITH_ACME)

    assert response.status_code == 200
    assert len(stored(client)) == 1
    assert len(spy.calls) == 1


def test_error_response_does_not_repeat_the_input(client):
    response = post(client, form(To="+15559999999", From="+15557654321"), SIGN_WITH_ACME)

    assert response.status_code == 404
    assert "1555" not in response.text


def test_missing_and_wrong_signatures_get_identical_responses(client):
    missing = post(client, form(), None)
    wrong = post(client, form(), "0" * 64)

    assert missing.status_code == wrong.status_code == 403
    assert missing.json() == wrong.json()


def test_unknown_tenant_returns_404(client):
    response = client.get("/tenants/no-such-firm/messages")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant"


def test_repeat_message_sid_returns_200_and_is_not_reclassified(client, spy):
    first = post(client, form(), SIGN_WITH_ACME)
    second = post(client, form(), SIGN_WITH_ACME)

    assert first.status_code == second.status_code == 200
    assert len(stored(client)) == 1
    assert len(spy.calls) == 1


def test_repeat_message_sid_keeps_the_first_body(client):
    post(client, form(Body="First"), SIGN_WITH_ACME)
    post(client, form(Body="Second"), SIGN_WITH_ACME)

    assert [message["body"] for message in stored(client)] == ["First"]


def test_repeat_message_sid_with_bad_signature_is_rejected(client):
    post(client, form(), SIGN_WITH_ACME)

    assert post(client, form(), "0" * 64).status_code == 403


def test_same_message_sid_is_stored_once_in_each_tenant(client):
    baker_body = form(To=BAKER_NUMBER)

    post(client, form(), SIGN_WITH_ACME)
    response = post(client, baker_body, sign(baker_body, BAKER_SECRET))

    assert response.status_code == 200
    assert len(stored(client, "acme-law")) == 1
    assert len(stored(client, "baker-llp")) == 1


@pytest.mark.parametrize(
    "body", [b"Body=caf%E9", b"Body=caf\xe9"], ids=["percent-encoded", "raw"]
)
def test_undecodable_text_is_stored_with_a_replacement_character(client, spy, body):
    response = post(client, form().replace(b"Body=Hello", body), SIGN_WITH_ACME)

    assert response.status_code == 200
    assert stored(client)[0]["body"] == "caf\ufffd"
    assert spy.calls == ["caf\ufffd"]


RACE_ROUNDS = 20


def deliver_in_pairs(monkeypatch, app, bodies):
    """Deliver each body twice, holding both deliveries just before the insert."""
    barrier = threading.Barrier(2)
    real_find_claimant = ingest.find_claimant

    def find_claimant_then_wait(conn, tenant_id, phone):
        claimant = real_find_claimant(conn, tenant_id, phone)
        barrier.wait(timeout=5)
        return claimant

    monkeypatch.setattr(ingest, "find_claimant", find_claimant_then_wait)
    statuses = []

    def deliver(body):
        client = TestClient(app, raise_server_exceptions=False)
        statuses.append(post(client, body, SIGN_WITH_ACME).status_code)

    for body in bodies:
        threads = [threading.Thread(target=deliver, args=(body,)) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    return statuses


def test_simultaneous_deliveries_store_one_row_and_classify_once(
    tmp_path, monkeypatch
):
    spy = SpyClassifier()
    app = create_app(str(tmp_path / "race.db"), spy)
    bodies = [form(MessageSid=f"SM{i}") for i in range(RACE_ROUNDS)]

    statuses = deliver_in_pairs(monkeypatch, app, bodies)

    assert statuses == [200] * RACE_ROUNDS * 2
    assert len(stored(TestClient(app))) == RACE_ROUNDS
    assert len(spy.calls) == RACE_ROUNDS


def test_simultaneous_stops_store_one_row_and_opt_out(tmp_path, monkeypatch):
    spy = SpyClassifier()
    db_path = str(tmp_path / "race.db")
    app = create_app(db_path, spy)
    bodies = [form(MessageSid=f"SM{i}", Body="STOP") for i in range(RACE_ROUNDS)]

    statuses = deliver_in_pairs(monkeypatch, app, bodies)

    assert statuses == [200] * RACE_ROUNDS * 2
    assert len(stored(TestClient(app))) == RACE_ROUNDS
    assert spy.calls == []
    with closing(connect(db_path)) as conn:
        rows = conn.execute("SELECT id FROM claimants WHERE opted_out = 1").fetchall()
    assert [row["id"] for row in rows] == ["C-100"]

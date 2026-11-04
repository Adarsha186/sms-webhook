from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from failure_data import BAKER_NUMBER, BAKER_SECRET, form, sign
from helpers import post, stored


def opted_out(db_path, claimant_id):
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT opted_out FROM claimants WHERE id = ?", (claimant_id,)
        ).fetchone()
    return bool(row["opted_out"])


def all_opted_out(db_path):
    with closing(connect(db_path)) as conn:
        rows = conn.execute("SELECT id FROM claimants WHERE opted_out = 1").fetchall()
    return [row["id"] for row in rows]


@pytest.mark.parametrize(
    "text",
    [
        "STOP",
        "stop",
        "Stop",
        "STOPALL",
        "stopall",
        "UNSUBSCRIBE",
        "unsubscribe",
        "  Unsubscribe  ",
        "STOP\n",
        "\tstop ",
    ],
)
def test_stop_keyword_opts_out_without_calling_classifier(client, spy, db_path, text):
    response = post(client, form(Body=text))

    assert response.status_code == 200
    assert spy.calls == []
    assert opted_out(db_path, "C-100")
    assert stored(client) == [
        {
            "message_sid": "SM1000",
            "claimant_id": "C-100",
            "body": text,
            "category": None,
            "needs_review": False,
            "dnc": True,
        }
    ]


@pytest.mark.parametrize("sid", ["SM.0001", "msg:abc", "S" * 65])
def test_signed_stop_with_unusual_message_sid_still_opts_out(client, db_path, sid):
    response = post(client, form(MessageSid=sid, Body="STOP"))

    assert response.status_code == 200
    assert opted_out(db_path, "C-100")


def test_stop_opts_out_only_that_claimant_in_that_tenant(client, db_path):
    post(client, form(Body="STOP"))

    assert all_opted_out(db_path) == ["C-100"]


def test_stop_to_other_tenant_opts_out_that_tenants_claimant(client, db_path):
    body = form(To=BAKER_NUMBER, Body="STOP")

    post(client, body, sign(body, BAKER_SECRET))

    assert all_opted_out(db_path) == ["C-200"]
    assert stored(client, "acme-law") == []


def test_stop_from_unmatched_number_is_stored_with_no_claimant(client, spy, db_path):
    response = post(client, form(From="+15559999999", Body="STOP"))

    assert response.status_code == 200
    assert spy.calls == []
    assert all_opted_out(db_path) == []
    message = stored(client)[0]
    assert message["claimant_id"] is None
    assert message["category"] is None
    assert message["dnc"] is True


@pytest.mark.parametrize(
    "text", ["STOP please", "don't stop", "stop!", "STOP STOP", "S TOP", "unsubscribed"]
)
def test_text_that_only_contains_a_keyword_is_classified_normally(
    client, spy, db_path, text
):
    post(client, form(Body=text))

    assert spy.calls == [text]
    assert all_opted_out(db_path) == []
    message = stored(client)[0]
    assert message["category"] == "other"
    assert message["dnc"] is False


def test_repeat_stop_returns_200_and_stores_one_row(client, db_path):
    first = post(client, form(Body="STOP"))
    second = post(client, form(Body="STOP"))

    assert first.status_code == second.status_code == 200
    assert len(stored(client)) == 1
    assert opted_out(db_path, "C-100")


def test_later_message_from_opted_out_claimant_keeps_the_flag(client, spy, db_path):
    post(client, form(MessageSid="SM1", Body="STOP"))
    post(client, form(MessageSid="SM2", Body="Hello"))

    assert opted_out(db_path, "C-100")
    assert spy.calls == ["Hello"]
    assert [message["dnc"] for message in stored(client)] == [True, True]


def test_earlier_message_shows_dnc_after_the_claimant_opts_out(client):
    post(client, form(MessageSid="SM1", Body="Hello"))
    post(client, form(MessageSid="SM2", Body="STOP"))

    assert [message["dnc"] for message in stored(client)] == [True, True]


def test_dnc_stays_false_for_another_claimant_in_the_tenant(client):
    post(client, form(MessageSid="SM1", Body="STOP"))
    post(client, form(MessageSid="SM2", From="+15551110002", Body="Hello"))

    assert [message["dnc"] for message in stored(client)] == [True, False]


def test_dnc_does_not_cross_to_the_shared_phone_in_another_tenant(client):
    baker_body = form(To=BAKER_NUMBER, Body="Hello")

    post(client, baker_body, sign(baker_body, BAKER_SECRET))
    post(client, form(Body="STOP"))

    assert stored(client, "baker-llp")[0]["dnc"] is False


def test_failed_opt_out_stores_nothing_so_a_retry_can_succeed(client, db_path):
    with closing(connect(db_path)) as conn:
        conn.execute(
            "CREATE TRIGGER block_opt_out BEFORE UPDATE ON claimants "
            "BEGIN SELECT RAISE(ABORT, 'opt-out failed'); END"
        )
        conn.commit()
    failing_client = TestClient(client.app, raise_server_exceptions=False)

    failed = post(failing_client, form(Body="STOP"))

    assert failed.status_code == 500
    assert stored(client) == []

    with closing(connect(db_path)) as conn:
        conn.execute("DROP TRIGGER block_opt_out")
        conn.commit()

    assert post(client, form(Body="STOP")).status_code == 200
    assert opted_out(db_path, "C-100")
    assert len(stored(client)) == 1

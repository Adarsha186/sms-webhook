import pytest
from fastapi.testclient import TestClient

from app.classifier import CATEGORIES
from app.main import create_app
from failure_data import SENDER, form
from helpers import SpyClassifier, post, stored


class BrokenClassifier:
    def classify(self, text):
        raise RuntimeError("model unavailable")


def client_with(db_path, classifier):
    return TestClient(create_app(db_path, classifier))


@pytest.mark.parametrize(
    "answer",
    ["banana", "", "Status_Question", " other", None, 42, ["other"], {"category": "other"}],
    ids=repr,
)
def test_bad_classifier_answer_stores_other_for_review(db_path, answer):
    client = client_with(db_path, SpyClassifier(answer=answer))

    response = post(client, form())

    assert response.status_code == 200
    message = stored(client)[0]
    assert message["category"] == "other"
    assert message["needs_review"] is True
    assert message["dnc"] is False


def test_classifier_error_stores_other_for_review(db_path):
    client = client_with(db_path, BrokenClassifier())

    response = post(client, form())

    assert response.status_code == 200
    message = stored(client)[0]
    assert message["category"] == "other"
    assert message["needs_review"] is True


@pytest.mark.parametrize("category", CATEGORIES)
def test_valid_answer_is_stored_without_review(db_path, category):
    client = client_with(db_path, SpyClassifier(answer=category))

    post(client, form())

    message = stored(client)[0]
    assert message["category"] == category
    assert message["needs_review"] is False


def test_classifier_receives_only_the_body_text(client, spy):
    post(client, form(Body="When is my hearing?"))

    assert spy.calls == ["When is my hearing?"]
    assert SENDER not in spy.calls[0]


def test_unmatched_sender_is_still_classified(client, spy):
    post(client, form(From="+15559999999", Body="Hello"))

    assert spy.calls == ["Hello"]

import time

from failure_data import SIGN_WITH_ACME, sign

CONTENT_TYPE = {"Content-Type": "application/x-www-form-urlencoded"}


class SpyClassifier:
    def __init__(self, delay: float = 0, answer: str = "other"):
        self.calls = []
        self.delay = delay
        self.answer = answer

    def classify(self, text):
        self.calls.append(text)
        time.sleep(self.delay)
        return self.answer


def post(client, body: bytes, signature=SIGN_WITH_ACME):
    headers = dict(CONTENT_TYPE)
    if signature == SIGN_WITH_ACME:
        headers["X-Signature"] = sign(body)
    elif signature is not None:
        headers["X-Signature"] = signature
    return client.post("/webhooks/sms", content=body, headers=headers)


def stored(client, tenant="acme-law"):
    return client.get(f"/tenants/{tenant}/messages").json()

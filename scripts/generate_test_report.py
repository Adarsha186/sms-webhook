"""Run every webhook case against the real app and write docs/test-report.md.

Usage: .venv/bin/python scripts/generate_test_report.py

Each case gets a fresh database. The report records what actually happened, and
a case passes only if its status, error code, stored row, opt-outs and classifier
calls all match. Exits non-zero if anything fails.
"""
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ElementTree
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from fastapi.testclient import TestClient  # noqa: E402

from app.classifier import CATEGORIES, KeywordClassifier  # noqa: E402
from app.db import connect  # noqa: E402
from app.main import create_app  # noqa: E402
from failure_data import (  # noqa: E402
    ACCEPTED_BODIES,
    BAD_SIGNATURES,
    BAKER_NUMBER,
    BAKER_SECRET,
    INVALID_MESSAGE_SIDS,
    MALFORMED_BODIES,
    MISSING_FIELDS,
    SIGN_WITH_ACME,
    UNKNOWN_NUMBERS,
    form,
    sign,
)
from helpers import SpyClassifier, post  # noqa: E402

BRIEF_BODY = (
    b"MessageSid=SM0001&From=%2B15551110001&To=%2B15550000001"
    b"&Body=When+is+my+hearing%3F"
)
BRIEF_SIGNATURE = "33599426679aaabb3e29c4291341f4c6e274c95f4333e604967a1d295e8e1054"
REQUEST_FIELDS = ("MessageSid", "From", "To", "Body")


class CountingKeywordClassifier:
    def __init__(self):
        self.calls = []

    def classify(self, text):
        self.calls.append(text)
        return KeywordClassifier().classify(text)


class BrokenClassifier:
    def __init__(self):
        self.calls = []

    def classify(self, text):
        self.calls.append(text)
        raise RuntimeError("model unavailable")


@dataclass
class Case:
    group: str
    name: str
    status: int
    deliveries: List[Tuple[bytes, object]] = field(default_factory=list)
    code: Optional[str] = None
    rows: int = 0
    stored: Optional[Dict] = None
    opted_out: Tuple[str, ...] = ()
    calls: int = 0
    classifier: Optional[object] = None
    get: Optional[str] = None
    get_body: Optional[object] = None
    concurrent: bool = False
    block_opt_out: bool = False
    same_response: bool = False
    not_in_response: Optional[str] = None
    classifier_saw: Optional[List[str]] = None


def message(category, claimant="C-100", needs_review=False, dnc=False):
    return {
        "claimant_id": claimant,
        "category": category,
        "needs_review": needs_review,
        "dnc": dnc,
    }


def signed(body):
    return [(body, SIGN_WITH_ACME)]


def build_cases() -> List[Case]:
    basic = "1. Basic flow"
    duplicates = "8. Duplicates"
    stop = "9. STOP and dnc"
    classifier = "10. Classifier failures"
    tenancy = "11. Tenant isolation"
    baker_body = form(To=BAKER_NUMBER)
    baker_stop = form(To=BAKER_NUMBER, Body="STOP")

    cases = [
        Case(basic, "Brief's signed example", 200, [(BRIEF_BODY, BRIEF_SIGNATURE)],
             rows=1, stored=message("status_question"), calls=1),
        Case(basic, "Status question about a case", 200,
             signed(form(Body="What is the status of my case?")),
             rows=1, stored=message("status_question"), calls=1),
        Case(basic, "Sender with no claimant", 200, signed(form(From="+15559999999")),
             rows=1, stored=message("other", claimant=None), calls=1),
        Case(basic, "Document message", 200, signed(form(Body="I have attached the document")),
             rows=1, stored=message("document_upload"), calls=1),
        Case(basic, "Schedule message", 200, signed(form(Body="Can we schedule a call?")),
             rows=1, stored=message("schedule_call"), calls=1),
        Case(basic, "Unrecognised message", 200, signed(form(Body="Thanks very much")),
             rows=1, stored=message("other"), calls=1),
        Case(basic, "GET after a delivery", 200, [(BRIEF_BODY, BRIEF_SIGNATURE)], rows=1, calls=1,
             get="/tenants/acme-law/messages",
             get_body=[{"message_sid": "SM0001", "claimant_id": "C-100",
                        "body": "When is my hearing?", "category": "status_question",
                        "needs_review": False, "dnc": False}]),
        Case(basic, "GET known tenant, no messages", 200, get="/tenants/baker-llp/messages",
             get_body=[]),
        Case(basic, "GET unknown tenant", 404, code="unknown_tenant",
             get="/tenants/no-such-firm/messages"),
    ]

    for group, failures in (
        ("2. Missing and empty fields", MISSING_FIELDS),
        ("3. Invalid MessageSid", INVALID_MESSAGE_SIDS),
        ("4. Malformed bodies", MALFORMED_BODIES),
        ("5. Unknown To", UNKNOWN_NUMBERS),
        ("6. Bad signatures", BAD_SIGNATURES),
    ):
        cases.append(Case(group, "Control: same request with nothing wrong", 200, signed(form()),
                          rows=1, stored=message("other"), calls=1))
        cases += [
            Case(group, f.id, f.status, [(f.body, f.signature)], code=f.code)
            for f in failures
        ]

    cases += [
        Case("6. Bad signatures", "Missing and wrong signatures get identical responses", 403,
             [(form(), None), (form(), "0" * 64)], code="invalid_signature", same_response=True),
        Case("5. Unknown To", "Error does not repeat the caller's numbers", 404,
             signed(form(To="+15559999999", From="+15557654321")), code="unknown_to",
             not_in_response="1555"),
    ]

    cases += [
        Case("7. Unusual but valid input", name, 200, signed(body), rows=1, calls=1)
        for name, body in ACCEPTED_BODIES.items()
    ]

    cases += [
        Case(duplicates, "Same delivery twice", 200, signed(form()) * 2, rows=1, calls=1),
        Case(duplicates, "Repeat with a different body keeps the first", 200,
             signed(form(Body="First")) + signed(form(Body="Second")),
             rows=1, stored={"body": "First"}, calls=1),
        Case(duplicates, "Repeat with a bad signature", 403,
             signed(form()) + [(form(), "0" * 64)], code="invalid_signature", rows=1, calls=1),
        Case(duplicates, "Same MessageSid in two tenants", 200,
             signed(form()) + [(baker_body, sign(baker_body, BAKER_SECRET))], rows=2, calls=2),
        Case(duplicates, "Two simultaneous deliveries", 200, signed(form()) * 2,
             rows=1, calls=1, concurrent=True),
        Case(duplicates, "Two simultaneous STOPs", 200, signed(form(Body="STOP")) * 2,
             rows=1, opted_out=("C-100",), stored=message(None, dnc=True), concurrent=True),
    ]

    stop_stored = message(None, dnc=True)
    for text in ("STOP", "stop", "Stop", "STOPALL", "stopall", "UNSUBSCRIBE", "unsubscribe",
                 "  Unsubscribe  ", "STOP\n", "\tstop "):
        cases.append(Case(stop, f"Keyword {text!r}", 200, signed(form(Body=text)),
                          rows=1, stored=stop_stored, opted_out=("C-100",)))
    cases += [
        Case(stop, "STOP with a dotted MessageSid", 200,
             signed(form(MessageSid="SM.0001", Body="STOP")),
             rows=1, stored=stop_stored, opted_out=("C-100",)),
        Case(stop, "STOP with a colon in MessageSid", 200,
             signed(form(MessageSid="msg:abc", Body="STOP")),
             rows=1, stored=stop_stored, opted_out=("C-100",)),
        Case(stop, "STOP with a 65-character MessageSid", 200,
             signed(form(MessageSid="S" * 65, Body="STOP")),
             rows=1, stored=stop_stored, opted_out=("C-100",)),
        Case(stop, "Opt-out fails, so the message is rolled back", 500,
             signed(form(Body="STOP")), block_opt_out=True),
        Case(stop, "Retry after a failed opt-out succeeds", 200,
             signed(form(Body="STOP")) * 2, rows=1, stored=stop_stored, opted_out=("C-100",),
             block_opt_out=True),
        Case(stop, "STOP from an unmatched number", 200,
             signed(form(From="+15559999999", Body="STOP")),
             rows=1, stored=message(None, claimant=None, dnc=True)),
        Case(stop, "Repeat STOP", 200, signed(form(Body="STOP")) * 2,
             rows=1, stored=stop_stored, opted_out=("C-100",)),
        Case(stop, "Later message after opt-out", 200,
             signed(form(MessageSid="SM1", Body="STOP"))
             + signed(form(MessageSid="SM2", Body="Thanks")),
             rows=2, stored=message("other", dnc=True), opted_out=("C-100",), calls=1),
        Case(stop, "Earlier message shows dnc after a later STOP", 200,
             signed(form(MessageSid="SM1", Body="Hello"))
             + signed(form(MessageSid="SM2", Body="STOP")),
             rows=2, opted_out=("C-100",), calls=1, get="/tenants/acme-law/messages",
             get_body=[
                 {"message_sid": "SM1", "claimant_id": "C-100", "body": "Hello",
                  "category": "other", "needs_review": False, "dnc": True},
                 {"message_sid": "SM2", "claimant_id": "C-100", "body": "STOP",
                  "category": None, "needs_review": False, "dnc": True},
             ]),
    ]
    for text in ("STOP please", "don't stop", "stop!", "STOP STOP", "S TOP", "unsubscribed"):
        cases.append(Case(stop, f"Not a keyword: {text!r}", 200, signed(form(Body=text)),
                          rows=1, stored=message("other"), calls=1))

    review = message("other", needs_review=True)
    for answer in ("banana", "", "Status_Question", " other", None, 42, ["other"],
                   {"category": "other"}):
        cases.append(Case(classifier, f"Answer {answer!r}", 200, signed(form()), rows=1,
                          stored=review, calls=1, classifier=SpyClassifier(answer=answer)))
    cases.append(Case(classifier, "Classifier raises an error", 200, signed(form()), rows=1,
                      stored=review, calls=1, classifier=BrokenClassifier()))
    for category in CATEGORIES:
        cases.append(Case(classifier, f"Valid answer {category!r}", 200, signed(form()), rows=1,
                          stored=message(category), calls=1,
                          classifier=SpyClassifier(answer=category)))
    cases.append(Case(classifier, "Classifier receives only the Body text", 200,
                      signed(form(Body="When is my hearing?")), rows=1, calls=1,
                      classifier_saw=["When is my hearing?"]))

    cases += [
        Case(tenancy, "Shared phone matches acme's claimant", 200, signed(form()),
             rows=1, stored=message("other", claimant="C-100"), calls=1),
        Case(tenancy, "Shared phone matches baker's claimant", 200,
             [(baker_body, sign(baker_body, BAKER_SECRET))],
             rows=1, stored=message("other", claimant="C-200"), calls=1),
        Case(tenancy, "Number known only to baker, sent to acme", 200,
             signed(form(From="+15551110003")),
             rows=1, stored=message("other", claimant=None), calls=1),
        Case(tenancy, "STOP to acme opts out only C-100", 200, signed(form(Body="STOP")),
             rows=1, stored=message(None, dnc=True), opted_out=("C-100",)),
        Case(tenancy, "STOP to baker opts out only C-200", 200,
             [(baker_stop, sign(baker_stop, BAKER_SECRET))],
             rows=1, stored=message(None, claimant="C-200", dnc=True), opted_out=("C-200",)),
        Case(tenancy, "dnc does not cross to the shared phone in baker", 200,
             [(baker_body, sign(baker_body, BAKER_SECRET))] + signed(form(Body="STOP")),
             rows=2, stored=message("other", claimant="C-200"), opted_out=("C-100",), calls=1),
        Case(tenancy, "GET shows only that tenant's messages", 200,
             [(baker_body, sign(baker_body, BAKER_SECRET))], rows=1, calls=1,
             get="/tenants/acme-law/messages", get_body=[]),
    ]
    return cases


def deliver_together(app, deliveries):
    barrier = threading.Barrier(len(deliveries))
    responses = []

    def deliver(body, signature):
        client = TestClient(app, raise_server_exceptions=False)
        barrier.wait()
        responses.append(post(client, body, signature))

    threads = [threading.Thread(target=deliver, args=item) for item in deliveries]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return responses


def set_opt_out_block(db_path: str, blocked: bool) -> None:
    statement = (
        "CREATE TRIGGER block_opt_out BEFORE UPDATE ON claimants "
        "BEGIN SELECT RAISE(ABORT, 'opt-out failed'); END"
        if blocked
        else "DROP TRIGGER block_opt_out"
    )
    with closing(connect(db_path)) as conn:
        conn.execute(statement)
        conn.commit()


def run(case: Case, directory: str, number: int) -> Dict:
    db_path = str(Path(directory) / f"case-{number}.db")
    classifier = case.classifier
    if classifier is None:
        classifier = (
            SpyClassifier(delay=0.1) if case.concurrent else CountingKeywordClassifier()
        )
    app = create_app(db_path, classifier)
    client = TestClient(app, raise_server_exceptions=False)

    if case.concurrent:
        responses = deliver_together(app, case.deliveries)
    else:
        responses = []
        for index, (body, sig) in enumerate(case.deliveries):
            if case.block_opt_out and index == 0:
                set_opt_out_block(db_path, True)
            responses.append(post(client, body, sig))
            if case.block_opt_out and index == 0:
                set_opt_out_block(db_path, False)
    if case.get:
        responses.append(client.get(case.get))
    response = responses[-1]

    rows = []
    for tenant in ("acme-law", "baker-llp"):
        rows += client.get(f"/tenants/{tenant}/messages").json()
    with closing(connect(db_path)) as conn:
        opted_out = tuple(
            row["id"]
            for row in conn.execute("SELECT id FROM claimants WHERE opted_out = 1 ORDER BY id")
        )

    expected_statuses = [case.status] if not case.concurrent else [case.status] * 2
    statuses = [r.status_code for r in responses]
    checks = [
        statuses[-len(expected_statuses):] == expected_statuses,
        len(rows) == case.rows,
        opted_out == case.opted_out,
        len(classifier.calls) == case.calls,
    ]
    if case.code:
        checks.append(response.json().get("error", {}).get("code") == case.code)
    if case.stored:
        checks.append(bool(rows) and all(rows[-1].get(k) == v for k, v in case.stored.items()))
    if case.get_body is not None:
        checks.append(response.json() == case.get_body)
    if case.same_response:
        checks.append(len({r.text for r in responses}) == 1)
    if case.not_in_response:
        checks.append(case.not_in_response not in response.text)
    if case.classifier_saw is not None:
        checks.append(classifier.calls == case.classifier_saw)

    return {
        "case": case,
        "response": response,
        "rows": rows,
        "opted_out": opted_out,
        "calls": len(classifier.calls),
        "inputs": list(classifier.calls),
        "passed": all(checks),
    }


def cell(value: object) -> str:
    text = str(value)
    if len(text) > 34:
        text = f"{text[:20]}... ({len(text)} chars)"
    text = text.encode("unicode_escape").decode("ascii") if not text.isprintable() else text
    return f"`{text}`".replace("|", "\\|") if text else "(empty)"


def request_cells(body: bytes) -> List[str]:
    parsed = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    cells = []
    for name in REQUEST_FIELDS:
        values = parsed.get(name)
        if values is None:
            cells.append("(missing)")
        elif len(values) > 1:
            cells.append(" and ".join(cell(v) for v in values))
        else:
            cells.append(cell(values[0]))
    return cells


def signature_cell(body: bytes, signature: object) -> str:
    if signature == SIGN_WITH_ACME or signature == sign(body):
        return "valid (acme)"
    if signature == sign(body, BAKER_SECRET):
        return "valid (baker)"
    if signature == BRIEF_SIGNATURE:
        return "valid (brief)"
    if signature is None:
        return "(missing)"
    return cell(repr(signature) if isinstance(signature, bytes) else signature)


def stored_cell(rows: List[Dict]) -> str:
    if not rows:
        return "nothing"
    row = rows[-1]
    summary = (
        f"claimant={row['claimant_id']}, category={row['category']}, "
        f"needs_review={row['needs_review']}, dnc={row['dnc']}"
    )
    return f"{len(rows)} row(s); last: {summary}"


def table_row(result: Dict) -> str:
    case = result["case"]
    response = result["response"]
    if case.get:
        request = [f"`GET {case.get}`", "", "", "", ""]
    else:
        body, signature = case.deliveries[-1]
        request = request_cells(body) + [signature_cell(body, signature)]
    deliveries = len(case.deliveries)
    name = case.name if deliveries < 2 else f"{case.name} ({deliveries} deliveries)"
    response_body = response.text or "(empty)"
    if len(response_body) > 90:
        response_body = f"{response_body[:80]}..."
    columns = [
        cell(name).strip("`"),
        *request,
        f"{case.status} / {response.status_code}",
        f"`{response_body}`".replace("|", "\\|") if response.text else "(empty)",
        stored_cell(result["rows"]),
        ", ".join(result["opted_out"]) or "none",
        str(result["calls"]),
        "PASS" if result["passed"] else "**FAIL**",
    ]
    return "| " + " | ".join(columns) + " |"


def run_pytest(directory: str) -> Dict:
    xml_path = Path(directory) / "pytest.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"--junitxml={xml_path}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
    )
    suite = ElementTree.parse(xml_path).getroot().find("testsuite")
    by_file: Dict[str, List[int]] = {}
    for test in suite.findall("testcase"):
        counts = by_file.setdefault(test.get("classname"), [0, 0])
        counts[0] += 1
        if test.find("failure") is not None or test.find("error") is not None:
            counts[1] += 1
    return {"total": int(suite.get("tests")), "by_file": by_file,
            "failed": int(suite.get("failures")) + int(suite.get("errors"))}


REFERENCE = """## Request and response fields

### `POST /webhooks/sms` request

| Field | Where | Rule |
|---|---|---|
| `MessageSid` | Form body | Required. 1 to 255 characters, no spaces or control characters |
| `From` | Form body | Required, not empty. No format check |
| `To` | Form body | Required, not empty. Must be a tenant's number |
| `Body` | Form body | Required, may be empty. Undecodable bytes become replacement characters |
| `X-Signature` | Header | Lowercase hex HMAC-SHA256 of the raw body, keyed with the tenant's secret |

### `POST /webhooks/sms` response

An accepted message returns 200 with an empty body.

### `GET /tenants/{tenant}/messages` response

| Field | Type | Meaning |
|---|---|---|
| `message_sid` | string | The provider's message ID |
| `claimant_id` | string or null | The matched claimant in this tenant |
| `body` | string | The text exactly as received |
| `category` | string or null | One of the four categories; null for STOP |
| `needs_review` | boolean | True when the classifier failed or gave a bad answer |
| `dnc` | boolean | True when the claimant has opted out, or the message is a STOP from an unmatched number |

### Error response

Every rejection returns `{"error": {"code": ..., "message": ...}}`.

| Status | `code` |
|---|---|
| 400 | `missing_field`, `repeated_field`, `invalid_message_sid` |
| 403 | `invalid_signature` |
| 404 | `unknown_to`, `unknown_tenant` |
"""

NOT_COVERED = """## What this report does not cover

- **Real server:** cases run through FastAPI's test client, not over a network.
- **Load:** the simultaneous cases use two deliveries, not sustained traffic.
- **Crash recovery:** a process dying mid-request isn't simulated here. The rollback of a failed
  opt-out is covered in `tests/test_stop.py`.
- **Race strength:** these recorded simultaneous cases only show the code behaves correctly. The
  regression check is in `tests/test_validation.py`, which holds deliveries at a barrier.
"""


def write_report(results: List[Dict], tests: Dict) -> int:
    passed = sum(1 for result in results if result["passed"])
    failed = len(results) - passed
    lines = [
        "# Test report",
        "",
        f"Generated on {date.today().isoformat()} by `scripts/generate_test_report.py`. "
        "Don't edit this file by hand.",
        "",
        "## Summary",
        "",
        "| Run | Total | Passed | Failed |",
        "|---|---|---|---|",
        f"| Recorded cases (below) | {len(results)} | {passed} | {failed} |",
        f"| pytest suite | {tests['total']} | {tests['total'] - tests['failed']} "
        f"| {tests['failed']} |",
        "",
        "Each recorded case runs against the real app with a fresh database. A case passes only "
        "if its status, error code, stored row, opt-outs and classifier calls all match. Every "
        "rejected case is also checked for no stored rows, no opt-outs and no classifier call.",
        "",
        "| pytest file | Tests | Failed |",
        "|---|---|---|",
    ]
    lines += [
        f"| `{name}` | {counts[0]} | {counts[1]} |"
        for name, counts in sorted(tests["by_file"].items())
    ]
    lines += ["", REFERENCE, "## Cases", "",
              "Status shows expected / actual. For a case with several deliveries, the request and "
              "response shown are from the last one. `Calls` counts classifier calls.", ""]

    groups: Dict[str, List[Dict]] = {}
    for result in results:
        groups.setdefault(result["case"].group, []).append(result)
    for group, group_results in groups.items():
        count = sum(1 for result in group_results if result["passed"])
        lines += [
            f"### {group} ({count} of {len(group_results)} passed)",
            "",
            "| Case | MessageSid | From | To | Body | X-Signature | Status | Response body "
            "| Stored | Opted out | Calls | Result |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        lines += [table_row(result) for result in group_results]
        lines.append("")
    lines.append(NOT_COVERED)

    output = ROOT / "docs" / "test-report.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"{passed} of {len(results)} cases passed; pytest {tests['total'] - tests['failed']} "
          f"of {tests['total']}; wrote {output.relative_to(ROOT)}")
    for result in results:
        if not result["passed"]:
            print("FAILED:", result["case"].group, "-", result["case"].name,
                  result["response"].status_code, result["response"].text[:120],
                  stored_cell(result["rows"]), result["opted_out"], result["calls"])
    return failed + tests["failed"]


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        results = [run(case, directory, i) for i, case in enumerate(build_cases())]
        tests = run_pytest(directory)
    return 1 if write_report(results, tests) else 0


if __name__ == "__main__":
    sys.exit(main())

# SMS Webhook Implementation Plan

**Goal:** Build `POST /webhooks/sms` and `GET /tenants/{tenant}/messages` to the brief, with tenant isolation and
safe handling of retries.

**Architecture:** FastAPI over SQLite. The database's unique constraint decides duplicates, and only the delivery that
wins the insert calls the classifier. `CLAUDE.md` holds the requirements, flow and design reasons; this file holds the
work split and the interface contract.

**Tech stack:** Python 3.9, FastAPI, SQLite, pytest, httpx.

This plan deliberately contains no application code: agents write all of it.

## Roles and handoffs

| Role | Owns | Handoff |
|---|---|---|
| Orchestrator (main session) | Dispatch, checking, all commits and pushes | Runs the full suite itself; never trusts a reported result alone |
| `builder` | `app/` | Reports files changed and real test output |
| `test-writer` | `tests/` | Reports coverage by requirement and real test output |
| `reviewer` | Nothing (read-only) | Reports at most five findings with failure scenarios |

`builder` and `test-writer` run in parallel: their directories don't overlap, and the contract below fixes the names
they share. `test-writer` does not read `app/`, so the tests are an independent check.

## Interface contract

Changing anything here needs the orchestrator's agreement, and both agents must be told.

### `app/main.py`
- `create_app(db_path: str, classifier) -> FastAPI`: runs `init_db` and seeds, then registers both routes.
- `app`: default instance, using `SMS_DB_PATH` (default `sms.db`) and `KeywordClassifier()`.

### `app/db.py`
- `connect(db_path: str) -> sqlite3.Connection`: new connection with WAL, `busy_timeout` and `sqlite3.Row`.
- `init_db(db_path: str) -> None`: creates tables and seeds the brief's data. Safe to rerun.
- `get_tenant_by_number(conn, number: str) -> Optional[sqlite3.Row]`
- `get_tenant(conn, tenant_id: str) -> Optional[sqlite3.Row]`
- `find_claimant(conn, tenant_id: str, phone: str) -> Optional[sqlite3.Row]`
- `list_messages(conn, tenant_id: str) -> List[dict]`: the six response fields, in insert order.

### Schema
- `tenants(id TEXT PRIMARY KEY, number TEXT UNIQUE NOT NULL, secret TEXT NOT NULL)`; `id` is the slug, such as `acme-law`.
- `claimants(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, phone TEXT NOT NULL, opted_out INTEGER NOT NULL DEFAULT 0,
  UNIQUE(tenant_id, phone))`
- `messages(id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, message_sid TEXT NOT NULL, claimant_id TEXT, body TEXT NOT
  NULL, category TEXT, needs_review INTEGER NOT NULL, UNIQUE(tenant_id, message_sid))`

### `app/security.py`
- `InvalidRequest(status: int, code: str, message: str)`: a `ValueError` that the app turns into the JSON error
  response.
- `parse_form(raw: bytes) -> Dict[str, str]`: raises `InvalidRequest` for a repeated field, a missing field, or an empty
  `MessageSid`, `From` or `To`. Undecodable bytes in `From`, `To` and `Body` become replacement characters. An empty `Body` is valid.
- `validate_message_sid(message_sid: str) -> None`: raises `InvalidRequest`. Runs after the signature check.
- `verify_signature(raw: bytes, secret: str, signature: Optional[str]) -> bool`: never raises.

### `app/classifier.py`
- `CATEGORIES`: the four allowed values.
- `KeywordClassifier.classify(text: str) -> str`
- `safe_classify(classifier, text: str) -> Tuple[str, bool]`: returns `(category, needs_review)` and never raises.

### `app/ingest.py`
- `is_stop(body: str) -> bool`
- `process_sms(db_path: str, classifier, tenant_id: str, form: Dict[str, str]) -> None`: flow steps 4 to 8 in `CLAUDE.md`.

### Test seams
Tests build apps with `create_app(str(tmp_path / "test.db"), fake_classifier)`, use the HTTP routes for behaviour, and
read `SELECT opted_out FROM claimants WHERE id = ?` through `connect` for the flag.

## Phase 2: build (25 minutes)

- [ ] **Task 1, `builder`:** `app/db.py` and `app/security.py`.
- [ ] **Task 2, `builder`:** `app/classifier.py`, `app/ingest.py` and `app/main.py`.
- [ ] **Task 3, `test-writer`, parallel with Tasks 1 and 2:** `tests/conftest.py` and the test files below.
- [ ] **Task 4, orchestrator:** run the full suite and send each failure to its owner. An application defect goes to
      `builder`. A suspected test defect goes to `test-writer`, which must explain why before any change.
- [ ] **Task 5, orchestrator:** read `git diff` against the traps in `CLAUDE.md`, commit, and push.

Commit after each task that leaves the suite no worse than before.

## Tests

This is the original test list. The final files are in `tests/`, grouped differently.

Items marked ★ are required by the brief. Every rejection test also asserts no rows were written and the classifier
was not called.

### `tests/test_signature.py`
- ★ Wrong signature returns 403; missing signature returns 403.
- The brief's signed example returns 200.
- Tampered body returns 403; a baker signature sent to an acme number returns 403.
- Each missing field returns 400; unknown `To` returns 404; a repeated field returns 400.
- A correctly signed body using `%20` or lowercase `%2b` returns 200.
- A non-ASCII `X-Signature` returns 403, not 500.

### `tests/test_idempotency.py`
- ★ Sequential repeat returns 200, with one row and one classifier call.
- ★ Two simultaneous deliveries both return 200, with one row and one classifier call.
- The same `MessageSid` in two tenants is stored once in each.
- A repeat with a different body keeps the first; a repeat with a bad signature returns 403.

### `tests/test_tenancy.py`
- ★ `+15551110001` matches C-100 through acme and C-200 through baker.
- A number known only to the other tenant is stored with no claimant.

### `tests/test_stop.py`
- ★ `STOP`, `stopall`, `  Unsubscribe  ` and `STOP\n` set the flag and skip the classifier, with a null category.
- ★ STOP to acme opts out C-100 and leaves C-200 untouched.
- STOP from an unmatched number is stored with no claimant.
- `STOP please` and `don't stop` are classified normally; a duplicate STOP causes no error.
- If the opt-out update fails, the message row is rolled back too.

### `tests/test_classifier.py`
- ★ `banana`, `None`, a list and `Status_Question` store `other` with `needs_review` true.
- A classifier exception does the same and returns 200.
- A genuine `other` answer has `needs_review` false.
- A spy confirms the classifier receives only the `Body` text.
- Messages from unmatched senders are still classified.

### `tests/test_messages_api.py`
- Known tenant with no messages returns `[]`; unknown tenant returns 404.
- Each item has exactly the six fields, and `needs_review` and `dnc` are JSON booleans.
- A tenant never sees another tenant's messages.

## How agent output is checked

1. The orchestrator reruns the suite rather than relying on the agent's report.
2. It reads the diff against the implementation traps in `CLAUDE.md`.
3. It confirms `tests/` wasn't weakened to get a pass.

## Phase 3: review (8 minutes)

- [ ] Dispatch `reviewer` and decide on up to two findings: fix, or accept with a stated reason.
- [ ] Have `builder` temporarily replace the atomic insert with select-then-insert, show the concurrency test failing,
      then restore the code with `git restore` and show the suite passing.
- [ ] Push, and prepare the answer on what breaks first in production.

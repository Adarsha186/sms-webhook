# Litigence SMS webhook

Multi-tenant service: claimants text their law firm's number, and the provider delivers each message to
`POST /webhooks/sms`. Many firms (tenants) share one service, so tenant isolation is a core requirement.

`sms-webhook-brief.md` is the source of truth, including seed data and the signed example. If this file and the
brief disagree, follow the brief and flag the conflict. Requirements may change partway through; when they do, update
this file in the same commit.

## Rules for agents

- Work only inside this repository. Do not read `.sf/` or anything outside the repo.
- All data is synthetic. Do not introduce other data or credentials.
- Direct dependencies are limited to: fastapi, uvicorn, httpx, pytest, python-multipart. Do not add others.
- Python is 3.9: use `Optional[str]`, not `str | None`.
- Do not weaken a test to hide a defect. If a test looks wrong, explain why before changing it.
- Write the failing test first, and commit after each working step.
- Do not build anything out of scope: auth on the GET route, a real SMS provider, a real model, a review UI, deployment.
- Do not log message bodies, phone numbers or secrets.

## Workflow

The plan is `docs/superpowers/plans/2026-11-04-sms-webhook.md`: it holds the task split, the interface contract and
the test list. Roles are in `.claude/agents/`. `builder` owns `app/`, `test-writer` owns `tests/`, `reviewer` is
read-only, and only the main session commits or pushes.

## Commands

- Install: `.venv/bin/python -m pip install -r requirements.txt`
- Test: `.venv/bin/python -m pytest -q`
- Run: `.venv/bin/python -m uvicorn app.main:app --reload`
- Test report: `.venv/bin/python scripts/generate_test_report.py` (writes `docs/test-report.md`)

## Requirements

### `POST /webhooks/sms`

Body is `application/x-www-form-urlencoded` with `MessageSid`, `From`, `To`, `Body`. Header `X-Signature` is the hex
HMAC-SHA256 of the original raw body bytes, keyed with the tenant's secret.

1. **Validation:** find the tenant from `To`, then check the signature over the original bytes before any write or
   classifier call. Missing field: 400. Unknown `To`: 404. Missing or wrong signature: 403. Accepted: 200.
2. **Idempotency:** a `MessageSid` is stored once per tenant, even when two deliveries arrive at the same moment. A
   repeat returns 200 and does not call the classifier again.
3. **Claimant matching:** match `From` within that tenant only. No match: store the message with no claimant.
4. **Opt-out:** `STOP`, `STOPALL` or `UNSUBSCRIBE` (any case, surrounding spaces allowed) sets that claimant's
   `opted_out` flag, in that tenant only. The flag covers every channel; no channel model is needed. STOP from an
   unmatched number is stored with no claimant. Never call the classifier for STOP messages.
5. **Classification:** every other message gets exactly one of `status_question`, `document_upload`, `schedule_call`,
   `other`. Use a deterministic local classifier with a replaceable `classify(text)` method. Pass it the `Body` text
   only, never claimant records or the `From`/`To` numbers. An answer outside the four values, or a classifier error,
   stores `other` with `needs_review` true.

### `GET /tenants/{tenant}/messages`

6. Returns that tenant's messages only, as a JSON array of `message_sid`, `claimant_id` (or null), `body`, `category`
   (null for STOP) and `needs_review`. Known tenant with no messages: `[]`. Unknown tenant: 404.
   **Added after the brief, at the user's request:** a `dnc` field meaning do not contact. It is true on
   every message from an opted-out claimant, including earlier ones, and on a STOP from an unmatched number.

### Tests

7. Required coverage: a bad signature, a duplicate `MessageSid`, the phone number shared across two tenants, STOP, and
   a bad classifier answer.

## Design decisions

### Webhook flow

1. Read the raw bytes and parse them without changing them. Unparseable or missing field: 400.
2. Look up the tenant from `To`. Unknown: 404.
3. Verify the HMAC over the raw bytes. Missing or wrong: 403.
4. Find the claimant by `tenant_id` and `From`.
5. STOP: in one transaction, insert the message and set `opted_out`. Return 200.
6. Otherwise, insert and commit with `category='other', needs_review=1`. If the row already existed, return 200.
7. Only the delivery that won the insert calls the classifier, outside any transaction.
8. If the answer is valid, update the row to that category with `needs_review=0`. Return 200.

### Why it works this way

- **The database decides duplicates.** `UNIQUE(tenant_id, message_sid)` with `INSERT ... ON CONFLICT DO NOTHING`, then
  check `rowcount`. Never select then insert: two simultaneous deliveries can both pass the select.
- **Insert before classifying.** This guarantees one classifier call per message, and no database lock is held during
  the call.
- **The inserted row is the safe outcome.** A classifier error needs no update, and a crash mid-request leaves the
  message flagged for review rather than lost.
- **STOP is one transaction.** If the message saved without the opt-out, the retry would look like a duplicate and the
  claimant would never be opted out.
- **Parse the raw body ourselves.** The signature covers the original bytes, so never rebuild or re-encode the body
  before verifying it.
- **Every claimant and message query filters by `tenant_id`.** The same phone number exists in more than one tenant.
- **The classifier is injected** through `create_app(db_path, classifier)` so tests can replace it.

### Decisions the brief leaves open

| Case | Decision | Reason |
|---|---|---|
| Missing field and bad signature together | 400 | Follows the brief's order; neither path writes |
| `Body=` present but empty | Accept; classifier returns `other` | The field is present, and an empty text is possible |
| Empty `MessageSid`, `From` or `To` | 400 | Unusable when empty |
| Repeated field (`To=a&To=b`) | 400 | Avoids ambiguity about which value was signed |
| Uppercase hex signature | 403 | Keeps the check strict and simple |
| `STOP please`, `don't stop` | Classify normally | Only an exact keyword match after stripping is a STOP |
| Opted-out claimant texts again | Store and classify; flag stays set | The brief defines no way to opt back in |
| Repeat `MessageSid` with different body | Keep the first version | The first stored delivery wins |
| Repeat `MessageSid` with bad signature | 403 | Signature checks run before duplicate checks |
| `MessageSid` format | 1 to 255 characters, no spaces, control characters or undecodable bytes, else 400, checked after the signature | The brief gives no format and rejecting a signed message loses it; never trim it |
| `From`, `To` format | Not checked beyond present and not empty | An unknown `To` must reach the 404, and an unmatched `From` is stored |
| Wrong `Content-Type` | Not rejected | The body decides: a non-form body fails as missing fields |
| Unknown extra fields | Ignored | Covered by the signature; providers add fields |
| Very large body | Accepted | The brief sets no limit, and a limit could lose a signed message |
| `Body` that isn't valid UTF-8 | Stored with replacement characters | A signed message is never lost; the signature covers the raw bytes |
| How STOP is detected | A rule before the classifier, not a fifth category | The brief forbids calling the model for STOP and requires a null category |
| How `dnc` is worked out | The claimant's `opted_out` flag, or a null category | Can't disagree with the flag; needs no migration. The null category covers an unmatched STOP, so if anything else ever gets a null category, change this |

### Error responses

Every rejection raises `InvalidRequest(status, code, message)`, which returns
`{"error": {"code": ..., "message": ...}}`. Messages never repeat the caller's input. Missing and wrong signatures
return an identical response. Checks run in this order: missing or repeated fields (400), 404, 403, then
`MessageSid` format (400). A format check must never run before the signature check.

## Implementation traps

- An `async def` route calling SQLite directly runs requests one at a time, so a race test could pass without proving
  anything. Read the body asynchronously, then run the work with `run_in_threadpool`.
- `sqlite3` connections are tied to one thread: open one per call, with WAL and `busy_timeout` set.
- `:memory:` gives each connection its own database. Concurrency tests need a temp file.
- `hmac.compare_digest` raises on non-ASCII strings. Compare bytes, so a bad header returns 403 rather than 500.
- `parse_qs` drops blank values unless `keep_blank_values=True`.
- Check that a classifier answer is a string before testing membership: a list raises `TypeError` against a set.
- Store `Body` exactly as received. Strip it only for the STOP check.
- SQLite stores `needs_review` as an integer. Return it as a JSON boolean.

## Planned layout

- `app/main.py`: `create_app`, routes, and the default `app`
- `app/db.py`: schema, seed data, connections, queries
- `app/security.py`: `parse_form`, `verify_signature`
- `app/classifier.py`: `KeywordClassifier`, `safe_classify`
- `app/ingest.py`: `is_stop`, `process_sms`
- `tests/`: one file per area (happy path, validation, STOP, classifier), with `failure_data.py`, `helpers.py` and
  `conftest.py`. `test_report_cases.py` runs every case from `scripts/generate_test_report.py`, so add report cases there

## Testing standards

- Every rejection test also asserts that no rows were written and the classifier was not called.
- The brief's signed example is a fixed test case.
- The concurrency test uses a file-backed database, a barrier held just before the insert, over repeated rounds, and asserts both responses
  are 200, with one row and one classifier call.
- A correctly signed body with different encoding (`%20` rather than `+`, or lowercase `%2b`) must return 200.
- A spy classifier confirms that it receives only the `Body` text.
- `tests/failure_data.py` is the catalogue of bad inputs. Add new cases there. Each is correctly signed unless the
  signature is the defect, so a rejection can only come from the defect the case names.

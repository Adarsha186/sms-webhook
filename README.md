# Litigence SMS webhook

A multi-tenant SMS webhook. Claimants text their law firm's number, and the service verifies each delivery, matches it
to a claimant in that firm, classifies it, and stores it for the firm to read. Many firms share one service, so one
firm's data must never affect another's.

It is built with Python, FastAPI and SQLite. All data is synthetic, and the secrets are test fixtures. The full
requirements are in [`sms-webhook-brief.md`](sms-webhook-brief.md).

## Status

**The brief's requirements are built and independently reviewed, with two rejection edge cases still open.** The review
found five issues: two are fixed and three are pending. All 231 tests pass, and
[`docs/test-report.md`](docs/test-report.md) records 120 cases with their requests and responses. Each recorded case
also runs as a test.

### Working end to end

Each flow runs from the HTTP request through the signature check and database to the GET response. All of them are
tested through the app. The first two, plus a duplicate and a forged STOP, were also checked on a running server.

| Flow | What happens |
|---|---|
| Normal message | Signature checked, claimant matched in that tenant, message stored, classified from `Body` only, returned by GET |
| STOP, `STOPALL`, `UNSUBSCRIBE` | Message stored with a null category and `dnc: true`, and `opted_out` set in the same transaction, with no classifier call |
| Unknown sender | Stored with no claimant; a STOP from one opts nobody out |
| Provider retry | Stored once per tenant and classified once, including simultaneous deliveries; returns 200 |
| Forged or missing signature | 403, with nothing stored, nobody opted out, and no classifier call |
| Classifier failure or bad answer | Message kept as `other` with `needs_review: true`; returns 200 |
| Malformed input | A JSON error with a stable code, not a 500 |
| Shared phone number | Matches only the claimant in the tenant that received the message |
| Reading messages | Only that tenant's messages; `[]` when there are none; 404 for an unknown tenant |

### Implemented, by requirement

| # | Requirement | Status |
|---|---|---|
| 1 | Validation order and status codes | Built, except the two open rejections under Pending |
| 2 | Idempotent delivery | Built |
| 3 | Claimant matching within the tenant | Built |
| 4 | STOP opt-out | Built |
| 5 | Classification and failure handling | Built |
| 6 | GET route | Built, with the added `dnc` field |
| 7 | Required tests | Built |

The review's fixes haven't been re-reviewed.

### Pending

| Item | Why it's open |
|---|---|
| Body over 16 KB returns 413 | The brief has no size limit, so a large signed message is lost, and an unsigned one gets 413 rather than 403. Needs a decision: keep the limit or remove it |
| Signed `Body` that isn't valid UTF-8 returns 400 | The message is lost. Needs a decision: reject it, or store it with replacement characters |
| Race test is unreliable | It missed a select-then-insert regression in 13 of 30 runs. The code itself passed; the test needs a tighter barrier |
| `dnc` meaning | It describes the message, so a later message from an opted-out claimant shows `false`. Needs a decision on whether it should follow the claimant |
| One `UPDATE` has no `tenant_id` filter | `app/ingest.py` uses a row ID from the same insert, so no failure is possible today. A one-line safeguard |
| Tests aren't independent | They were written in the same session as the code. `test-writer` should check coverage from the brief |

## How to run

You need Python 3.9 or later. Run these from the project root.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Run the tests:

```bash
.venv/bin/python -m pytest -q
```

Regenerate the test report, which records each case's request and response in `docs/test-report.md`:

```bash
.venv/bin/python scripts/generate_test_report.py
```

Start the server. It creates and seeds `sms.db` in the project root, or the path in `SMS_DB_PATH`:

```bash
.venv/bin/python -m uvicorn app.main:app
```

In a second terminal, send the brief's signed example:

```bash
curl -i -X POST http://127.0.0.1:8000/webhooks/sms \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'X-Signature: 33599426679aaabb3e29c4291341f4c6e274c95f4333e604967a1d295e8e1054' \
  --data-binary 'MessageSid=SM0001&From=%2B15551110001&To=%2B15550000001&Body=When+is+my+hearing%3F'
```

Then read it back:

```bash
curl http://127.0.0.1:8000/tenants/acme-law/messages
```

```json
[{"message_sid":"SM0001","claimant_id":"C-100","body":"When is my hearing?","category":"status_question","needs_review":false,"dnc":false}]
```

Sending the same example again returns 200 and stores nothing new. To start again, stop the server and delete `sms.db`, `sms.db-wal` and `sms.db-shm`.

## API

### `POST /webhooks/sms`

The body is `application/x-www-form-urlencoded` with `MessageSid`, `From`, `To` and `Body`. The `X-Signature` header is
the hex HMAC-SHA256 of the raw body bytes, keyed with the tenant's secret.

### `GET /tenants/{tenant}/messages`

Returns that tenant's messages as a JSON array of `message_sid`, `claimant_id`, `body`, `category`, `needs_review` and
`dnc`. `category` is null for STOP messages. `dnc` is true when that message is a STOP, and false otherwise.
This route has no authentication, which the brief puts out of scope.

### Errors

Every rejection returns the same JSON shape. Messages never repeat the caller's input, because that input can contain
phone numbers.

```json
{"error": {"code": "missing_field", "message": "Body is required."}}
```

| Status | Code | Meaning |
|---|---|---|
| 400 | `missing_field` | A field is absent, or `MessageSid`, `From` or `To` is empty |
| 400 | `repeated_field` | A required field appears more than once |
| 400 | `invalid_encoding` | The body is not valid UTF-8 |
| 400 | `invalid_message_sid` | `MessageSid` is over 255 characters, or contains spaces or control characters |
| 403 | `invalid_signature` | The signature is missing or wrong; both get the same response |
| 404 | `unknown_to` | No tenant uses that number |
| 404 | `unknown_tenant` | GET for a tenant that doesn't exist |
| 413 | `request_too_large` | The body is over 16 KB |

Checks run in this order: 413, missing or malformed input (400), 404, 403, then `MessageSid` format (400). None of them
writes anything. The format check runs last so it can't replace a 403 or 404 the brief requires.

## How it works

| File | Responsibility |
|---|---|
| `app/main.py` | Builds the app and defines the routes |
| `app/security.py` | Parses the raw body and verifies the signature |
| `app/ingest.py` | Matches the claimant, stores the message and classifies it |
| `app/classifier.py` | Deterministic keyword classifier |
| `app/db.py` | Schema, seed data, connections and queries |

A delivery is handled in this order:

1. Read the raw bytes and parse them.
2. Find the tenant from `To`.
3. Verify the signature, then check the `MessageSid` format. Nothing is written before these pass.
4. Find the claimant within that tenant.
5. If the text is a STOP keyword, store the message and set `opted_out` in one transaction, then finish. The classifier
   is not called.
6. Otherwise, insert and commit the message as `other`, flagged for review. If it already exists, finish.
7. Call the classifier with the `Body` text only.
8. If the answer is valid, update the row with the category and clear the review flag.

## How the design decisions were made

Each decision started from a way the system could fail. The brief's requirements were read as failure scenarios first
(a retry, a shared phone number, a crash mid-request), and the design had to make that failure hard or impossible.

| Decision | The failure it prevents |
|---|---|
| Verify the signature over the original bytes, parsed by hand rather than by a form library | The body is re-encoded before checking, so a genuine signature fails |
| Compare signatures as bytes, in constant time | A timing leak, or a non-ASCII header crashing the check |
| Filter every claimant and message query by `tenant_id` | `+15551110001` belongs to claimants in both firms, so a lookup by phone alone can pick the wrong one |
| Store the message before classifying it | A classifier failure or crash loses the message; it stays flagged for review instead |
| Classify outside any database transaction | A slow classifier holds SQLite's single write lock and blocks every other delivery |
| Inject the classifier through `create_app(db_path, classifier)` | Tests can't replace it, so failure paths can't be exercised |
| Run database work in a threadpool | Blocking calls in an `async` route process requests one at a time, which would also let a race test pass without proving anything |
| Open one SQLite connection per call, using WAL and a busy timeout | Connections shared across threads fail, and simultaneous writers fail immediately rather than waiting |
| Let the database decide duplicates, using `INSERT ... ON CONFLICT DO NOTHING` and checking the row count | Two simultaneous deliveries both pass a select-then-insert check, and both call the classifier |
| Reject a `MessageSid` containing spaces or control characters rather than trimming it | `SM1` and `SM1 ` count as different messages, so a retry slips past the duplicate check |
| Check the `MessageSid` format only after the signature, and keep the rule loose | A strict check before the signature lost signed STOPs and replaced required 403 and 404 responses; the review found this |
| Give missing and wrong signatures an identical response | The response reveals how close a forged request came |
| Keep error messages free of the caller's input | Phone numbers leak into responses and logs |
| Save a STOP message and its opt-out in one transaction | If only the message saves, the retry looks like a duplicate and the claimant is never opted out |
| Treat any invalid classifier answer as `other` with `needs_review` true | Bad output reaches stored data as if it were a real category |
| Detect STOP with a rule before the classifier, not as a fifth category | The brief forbids calling the model for STOP, and a model could misread an opt-out |
| Derive `dnc` from the null category rather than storing it | Two stored values could disagree, and existing databases would need a migration |

### Where the brief was silent

These were judgment calls, chosen to be strict and predictable:

| Case | Decision | Reason |
|---|---|---|
| Missing field and bad signature together | 400 | Follows the brief's order; neither path writes |
| `Body=` present but empty | Accept; classified as `other` | The field is present, and an empty text is possible |
| Repeated field (`To=a&To=b`) | 400 | Avoids ambiguity about which value was signed |
| `STOP please`, `don't stop` | Classify normally | Only an exact keyword after stripping is an opt-out |
| Opted-out claimant texts again | Store and classify; the flag stays set | The brief defines no way to opt back in |
| Repeat `MessageSid` with a different body | Keep the first | The first stored delivery wins |
| `MessageSid` format | 1 to 255 characters, no spaces or control characters | The brief gives no format, and rejecting a signed message loses it, so this blocks only values that can't be a stable ID |
| `From` and `To` format | Not checked, beyond being present and not empty | The brief wants an unknown `To` to return 404 and an unmatched `From` to be stored, and senders can be short codes |
| Wrong `Content-Type` | Not rejected | The body decides: a non-form body fails as missing fields |
| Unknown extra fields | Ignored | They are covered by the signature, and providers often add fields |
| Body over 16 KB | 413 | Far above any SMS, and limits what an unauthenticated caller can send |

`CLAUDE.md` has the full list.

## How it was built

This project was built by directing coding agents, as the brief requires.

- **Instructions:** [`CLAUDE.md`](CLAUDE.md) holds the requirements, design rules and known implementation traps.
- **Plan:** [`docs/superpowers/plans/2026-11-04-sms-webhook.md`](docs/superpowers/plans/2026-11-04-sms-webhook.md) holds
  the task split, the test list and an interface contract, so application code and tests can be written in parallel.
- **Roles:** `.claude/agents/` defines `builder` (owns `app/`), `test-writer` (owns `tests/`, works from the brief without
  reading `app/`) and `reviewer` (no write tools). The `app/` and `tests/` ownership is set by instruction, not enforced
  by tools.
- **Permissions:** `.claude/settings.json` keeps agents inside the repository, sandboxes shell commands, blocks web
  access, and requires approval for pushes. Agents can't edit these settings.

The code so far was written test-first in the main session, not by the separate `builder` and `test-writer` agents, so
its tests are not yet an independent check of the code.

### Independent review

An agent that didn't write the code reviewed it against the brief, running as a read-only `Plan` agent that followed
`.claude/agents/reviewer.md`, because that definition hadn't loaded in the session. The brief allows acting on up to two
findings:

| # | Finding | Decision |
|---|---|---|
| 1 | Format checks rejected messages the brief requires, including signed STOPs | Fixed. The tests that asserted this were wrong, because they required a 400 where the brief requires a 200, 403 or 404 |
| 2 | No test covered a forged STOP | Fixed. Putting a STOP signature bypass back in now fails exactly the three new cases |
| 3 | The race test misses a select-then-insert regression 13 times in 30 | Pending. The production code passed |
| 4 | The size limit and non-UTF-8 rejection lose messages | Pending. Needs a decision |
| 5 | One `UPDATE` has no `tenant_id` filter | Pending. No failure is possible today |

Two tests have been shown to fail when their protection is removed: splitting the STOP transaction fails the rollback
test, and letting STOP skip the signature check fails the forged-STOP cases.

## Known limitations

- Secrets are stored in plain text in SQLite. That's acceptable for synthetic fixtures only.
- The 16 KB limit is checked after the body is read, so it doesn't stop a very large upload reaching memory.
- Until the `dnc` decision is made, sending code must check `opted_out`, not `dnc`.
- A STOP reusing an already stored `MessageSid` returns 200 without opting out, under the "first delivery wins" rule.
  Genuine retries repeat the same message, so this shouldn't happen in practice.
- Importing `app.main` creates `sms.db`, including during tests. Git ignores it.
- If a process crashes between storing and classifying, the message stays as `other` for review and is not retried.

## What would break first in production

Classifying inside the webhook request. A slow real model would push requests past the provider's timeout, which
triggers more retries and more load, all competing for SQLite's single writer. The fix is to acknowledge quickly,
classify from a queue, and move to Postgres.

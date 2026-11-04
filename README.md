# Litigence SMS webhook

A multi-tenant SMS webhook. Claimants text their law firm's number, and the service verifies each delivery, matches it
to a claimant in that firm, classifies it, and stores it for the firm to read. Many firms share one service, so one
firm's data must never affect another's.

It is built with Python, FastAPI and SQLite. All data is synthetic, and the secrets are test fixtures. The full
requirements are in [`sms-webhook-brief.md`](sms-webhook-brief.md).

## Status

**This is a working happy path, not a finished feature.** It does not meet the brief yet.

| Behaviour | Status |
|---|---|
| Signed message is stored, classified and listed | Done |
| Sender matched within the tenant only; no match stores no claimant | Done |
| Wrong signature returns 403 and stores nothing | Done |
| Known tenant with no messages returns `[]` | Done |
| Missing signature returns 403 | Works, no test yet |
| Duplicate `MessageSid` returns 200 without reclassifying | **Not built:** returns 500 |
| `STOP`, `STOPALL`, `UNSUBSCRIBE` opt-out | **Not built:** classified like any other text |
| Bad classifier answer or error stores `other` for review | **Not built:** a bad answer is stored as the category; an error returns 500 |
| Missing field returns 400 | **Not built:** returns 500, or 403 if `To` is present and the signature is bad |
| Unknown `To` returns 404 | **Not built:** returns 500 |
| Unknown tenant on GET returns 404 | **Not built:** returns `[]` |

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
[{"message_sid":"SM0001","claimant_id":"C-100","body":"When is my hearing?","category":"status_question","needs_review":false}]
```

Sending the same example twice returns 500 until duplicate handling is built. To start again, stop the server and
delete `sms.db`, `sms.db-wal` and `sms.db-shm`.

## API

### `POST /webhooks/sms`

The body is `application/x-www-form-urlencoded` with `MessageSid`, `From`, `To` and `Body`. The `X-Signature` header is
the hex HMAC-SHA256 of the raw body bytes, keyed with the tenant's secret.

### `GET /tenants/{tenant}/messages`

Returns that tenant's messages as a JSON array of `message_sid`, `claimant_id`, `body`, `category` and `needs_review`.
This route has no authentication, which the brief puts out of scope.

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
3. Verify the signature. Nothing is written before this passes.
4. Find the claimant within that tenant.
5. Insert and commit the message as `other`, flagged for review.
6. Call the classifier with the `Body` text only.
7. Update the row with the category and clear the review flag.

## How the design decisions were made

Each decision started from a way the system could fail. The brief's requirements were read as failure scenarios first
(a retry, a shared phone number, a crash mid-request), and the design had to make that failure hard or impossible.

### Built

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

### Planned

| Decision | The failure it prevents |
|---|---|
| Let the database decide duplicates, using `INSERT ... ON CONFLICT DO NOTHING` and checking the row count | Two simultaneous deliveries both pass a select-then-insert check, and both call the classifier |
| Save a STOP message and its opt-out in one transaction | If only the message saves, the retry looks like a duplicate and the claimant is never opted out |
| Treat any invalid classifier answer as `other` with `needs_review` true | Bad output reaches stored data as if it were a real category |

The `UNIQUE(tenant_id, message_sid)` constraint is already in the schema, which is why a duplicate currently fails
with a 500 rather than storing a second row.

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

None of these is built yet except where the status table says so. `CLAUDE.md` has the full list.

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

The happy path so far was written test-first in the main session, not by the separate `builder` and `test-writer`
agents, so its tests are not yet an independent check of the code.

## Known limitations

- Secrets are stored in plain text in SQLite. That's acceptable for synthetic fixtures only.
- Importing `app.main` creates `sms.db`, including during tests. Git ignores it.
- If a process crashes between storing and classifying, the message stays as `other` for review and is not retried.

## What would break first in production

Classifying inside the webhook request. A slow real model would push requests past the provider's timeout, which
triggers more retries and more load, all competing for SQLite's single writer. The fix is to acknowledge quickly,
classify from a queue, and move to Postgres.

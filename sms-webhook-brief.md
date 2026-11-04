# Litigence live exercise: build a feature by directing coding agents (43 minutes)

## How this works

- Agents write all application and test code, including any temporary edits to prove a test catches a bug. You
  may hand-write instruction files (CLAUDE.md, AGENTS.md), agent definitions, plans, prompts, configuration and
  shell commands. Reading code and directing targeted fixes is expected.
- Use Claude Code, Codex, or both. Start from an empty git repository. Python, SQLite, and FastAPI or Flask. Allowed
  direct dependencies: fastapi or flask, uvicorn, httpx, pytest, and python-multipart for form parsing; their own
  dependencies are fine. Commit as you go, and push to a GitHub repository (public, or shared with us) at the end
  of each phase; paste the link in the chat.
- Keep agents limited to this repository, and tell us what permission settings you chose and why.
- **Phase 1, setup (10 minutes, including a 2-minute walkthrough to us).** Before any application code exists, set
  the repository up for agents: instruction files, any subagents or roles, and a plan.
- **Phase 2, build (25 minutes).** Have your agents build the feature. Tell us how you split the work, how agents
  hand off, and how you check what they produce.
- **Phase 3, review (8 minutes).** Have the work reviewed by an agent that did not write it, and decide what to do
  with up to two findings. Also show us one test failing when the protection it covers is removed.
- We are judging your setup and how you direct and check the agents. An unfinished feature is fine. Requirements
  may change partway through, as they do with customers.
- Everything below is synthetic. Do not give your agents any other data or credentials.

## Context

Litigence runs many law firms (tenants) on one service. Claimants text their firm's phone number.

## The feature

`POST /webhooks/sms`, body `application/x-www-form-urlencoded` with fields `MessageSid`, `From`, `To`, `Body`.
Header `X-Signature` = hex HMAC-SHA256 of the original raw body bytes, keyed with the tenant's secret. This is a
synthetic scheme for the exercise, not a real provider's.

Seed data (all synthetic; the secrets are test fixtures):

| Tenant | Number | Secret |
|---|---|---|
| acme-law | +15550000001 | acme-secret |
| baker-llp | +15550000002 | baker-secret |

| Claimant | Tenant | Phone |
|---|---|---|
| C-100 | acme-law | +15551110001 |
| C-101 | acme-law | +15551110002 |
| C-200 | baker-llp | +15551110001 |
| C-201 | baker-llp | +15551110003 |

Signed example (correct signature for acme-law):

```
body:        MessageSid=SM0001&From=%2B15551110001&To=%2B15550000001&Body=When+is+my+hearing%3F
X-Signature: 33599426679aaabb3e29c4291341f4c6e274c95f4333e604967a1d295e8e1054
```

## Requirements

1. Parse the body to find the tenant from `To`, then check the signature over the original bytes before any write
   or model call. A missing field returns 400; an unknown `To` returns 404; a missing or wrong signature returns
   403. Accepted messages return 200.
2. The provider retries deliveries, sometimes two at the same moment. A `MessageSid` is stored once per tenant,
   even when two deliveries arrive together. A repeat returns 200 and does not call the model again.
3. Match `From` to a claimant in that tenant only. No match: store the message with no claimant.
4. `STOP`, `STOPALL` or `UNSUBSCRIBE` (any case, surrounding spaces allowed) sets the claimant's `opted_out` flag,
   which covers every channel; no channel model is needed. Only that claimant, in that tenant, is opted out. STOP
   from an unmatched number is stored with no claimant. Never call the model for STOP messages.
5. Every other message is classified into exactly one of `status_question`, `document_upload`, `schedule_call`,
   `other`. No real model: use a deterministic local classifier with a `classify(text)` method that tests can
   replace. Pass it the `Body` text only, never claimant records or the `From`/`To` numbers. An answer outside the
   four values, or a classifier error, stores `other` with `needs_review` true. (Detecting names typed inside the
   text is out of scope.)
6. `GET /tenants/{tenant}/messages` returns that tenant's messages only, as a JSON array with `message_sid`,
   `claimant_id` (or null), `body`, `category` (null for STOP) and `needs_review`. A known tenant with no messages
   returns `[]`; an unknown tenant returns 404.
7. Tests for: a bad signature, a duplicate `MessageSid`, the phone number shared across two tenants, STOP, and a
   bad classifier answer. Do not weaken a test to hide a defect; if a test is wrong, say why before changing it.

Out of scope: authentication on the GET route, a real SMS provider, a real model, a review UI, deployment.

At the end we will ask what you think would break first in production.

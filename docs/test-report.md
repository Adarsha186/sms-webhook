# Test report

Generated on 2026-11-04 by `scripts/generate_test_report.py`. Don't edit this file by hand.

## Summary

| Run | Total | Passed | Failed |
|---|---|---|---|
| Recorded cases (below) | 122 | 122 | 0 |
| pytest suite | 236 | 236 | 0 |

Each recorded case runs against the real app with a fresh database. A case passes only if its status, error code, stored row, opt-outs and classifier calls all match. Every rejected case is also checked for no stored rows, no opt-outs and no classifier call.

| pytest file | Tests | Failed |
|---|---|---|
| `tests.test_classifier` | 15 | 0 |
| `tests.test_happy_path` | 9 | 0 |
| `tests.test_report_cases` | 122 | 0 |
| `tests.test_stop` | 28 | 0 |
| `tests.test_validation` | 62 | 0 |

## Request and response fields

### `POST /webhooks/sms` request

| Field | Where | Rule |
|---|---|---|
| `MessageSid` | Form body | Required. 1 to 255 characters, no spaces or control characters |
| `From` | Form body | Required, not empty. No format check |
| `To` | Form body | Required, not empty. Must be a tenant's number |
| `Body` | Form body | Required, may be empty |
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
| 400 | `missing_field`, `repeated_field`, `invalid_encoding`, `invalid_message_sid` |
| 403 | `invalid_signature` |
| 404 | `unknown_to`, `unknown_tenant` |
| 413 | `request_too_large` |

## Cases

Status shows expected / actual. For a case with several deliveries, the request and response shown are from the last one. `Calls` counts classifier calls.

### 1. Basic flow (9 of 9 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Brief's signed example | `SM0001` | `+15551110001` | `+15550000001` | `When is my hearing?` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=status_question, needs_review=False, dnc=False | none | 1 | PASS |
| Status question about a case | `SM1000` | `+15551110001` | `+15550000001` | `What is the status of my case?` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=status_question, needs_review=False, dnc=False | none | 1 | PASS |
| Sender with no claimant | `SM1000` | `+15559999999` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=None, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Document message | `SM1000` | `+15551110001` | `+15550000001` | `I have attached the document` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=document_upload, needs_review=False, dnc=False | none | 1 | PASS |
| Schedule message | `SM1000` | `+15551110001` | `+15550000001` | `Can we schedule a call?` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=schedule_call, needs_review=False, dnc=False | none | 1 | PASS |
| Unrecognised message | `SM1000` | `+15551110001` | `+15550000001` | `Thanks very much` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| GET after a delivery | `GET /tenants/acme-law/messages` |  |  |  |  | 200 / 200 | `[{"message_sid":"SM0001","claimant_id":"C-100","body":"When is my hearing?","cat...` | 1 row(s); last: claimant=C-100, category=status_question, needs_review=False, dnc=False | none | 1 | PASS |
| GET known tenant, no messages | `GET /tenants/baker-llp/messages` |  |  |  |  | 200 / 200 | `[]` | nothing | none | 0 | PASS |
| GET unknown tenant | `GET /tenants/no-such-firm/messages` |  |  |  |  | 404 / 404 | `{"error":{"code":"unknown_tenant","message":"No such tenant."}}` | nothing | none | 0 | PASS |

### 2. Missing and empty fields (11 of 11 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Control: same reques... (40 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| missing-message-sid | (missing) | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"missing_field","message":"MessageSid is required."}}` | nothing | none | 0 | PASS |
| missing-from | `SM1000` | (missing) | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"missing_field","message":"From is required."}}` | nothing | none | 0 | PASS |
| missing-to | `SM1000` | `+15551110001` | (missing) | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"missing_field","message":"To is required."}}` | nothing | none | 0 | PASS |
| missing-body | `SM1000` | `+15551110001` | `+15550000001` | (missing) | valid (acme) | 400 / 400 | `{"error":{"code":"missing_field","message":"Body is required."}}` | nothing | none | 0 | PASS |
| empty-request | (missing) | (missing) | (missing) | (missing) | valid (acme) | 400 / 400 | `{"error":{"code":"missing_field","message":"MessageSid is required."}}` | nothing | none | 0 | PASS |
| json-instead-of-form | (missing) | (missing) | (missing) | (missing) | valid (acme) | 400 / 400 | `{"error":{"code":"missing_field","message":"MessageSid is required."}}` | nothing | none | 0 | PASS |
| empty-message-sid | (empty) | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"missing_field","message":"MessageSid is required."}}` | nothing | none | 0 | PASS |
| empty-from | `SM1000` | (empty) | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"missing_field","message":"From is required."}}` | nothing | none | 0 | PASS |
| empty-to | `SM1000` | `+15551110001` | (empty) | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"missing_field","message":"To is required."}}` | nothing | none | 0 | PASS |
| missing-field-unsigned | `SM1000` | `+15551110001` | `+15550000001` | (missing) | (missing) | 400 / 400 | `{"error":{"code":"missing_field","message":"Body is required."}}` | nothing | none | 0 | PASS |

### 3. Invalid MessageSid (8 of 8 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Control: same reques... (40 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| sid-only-spaces | `   ` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"invalid_message_sid","message":"MessageSid must be 1 to 255 ch...` | nothing | none | 0 | PASS |
| sid-inner-space | `SM 1` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"invalid_message_sid","message":"MessageSid must be 1 to 255 ch...` | nothing | none | 0 | PASS |
| sid-trailing-space | `SM1 ` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"invalid_message_sid","message":"MessageSid must be 1 to 255 ch...` | nothing | none | 0 | PASS |
| sid-trailing-newline | `SM1\n` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"invalid_message_sid","message":"MessageSid must be 1 to 255 ch...` | nothing | none | 0 | PASS |
| sid-nul-byte | `SM\x001` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"invalid_message_sid","message":"MessageSid must be 1 to 255 ch...` | nothing | none | 0 | PASS |
| sid-too-long | `SSSSSSSSSSSSSSSSSSSS... (256 chars)` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"invalid_message_sid","message":"MessageSid must be 1 to 255 ch...` | nothing | none | 0 | PASS |
| sid-sql-text | `SM1'; DROP TABLE messages;--` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"invalid_message_sid","message":"MessageSid must be 1 to 255 ch...` | nothing | none | 0 | PASS |

### 4. Malformed bodies (6 of 6 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Control: same reques... (40 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| repeated-to | `SM1000` | `+15551110001` | `+15550000001` and `+15550000002` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"repeated_field","message":"To appears more than once."}}` | nothing | none | 0 | PASS |
| repeated-sid | `SM1000` and `SM2` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 400 / 400 | `{"error":{"code":"repeated_field","message":"MessageSid appears more than once."}}` | nothing | none | 0 | PASS |
| raw-invalid-utf8 | (missing) | (missing) | (missing) | (missing) | valid (acme) | 400 / 400 | `{"error":{"code":"invalid_encoding","message":"The body is not valid UTF-8."}}` | nothing | none | 0 | PASS |
| percent-encoded-invalid-utf8 | `SM1000` | `+15551110001` | `+15550000001` | `�` | valid (acme) | 400 / 400 | `{"error":{"code":"invalid_encoding","message":"The body is not valid UTF-8."}}` | nothing | none | 0 | PASS |
| request-too-large | `SM1000` | `+15551110001` | `+15550000001` | `xxxxxxxxxxxxxxxxxxxx... (20000 chars)` | valid (acme) | 413 / 413 | `{"error":{"code":"request_too_large","message":"The body is too large."}}` | nothing | none | 0 | PASS |

### 5. Unknown To (7 of 7 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Control: same reques... (40 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| unknown-to | `SM1000` | `+15551110001` | `+15559999999` | `Hello` | valid (acme) | 404 / 404 | `{"error":{"code":"unknown_to","message":"No tenant uses that number."}}` | nothing | none | 0 | PASS |
| to-is-not-a-number | `SM1000` | `+15551110001` | `not-a-number` | `Hello` | valid (acme) | 404 / 404 | `{"error":{"code":"unknown_to","message":"No tenant uses that number."}}` | nothing | none | 0 | PASS |
| unknown-to-unsigned | `SM1000` | `+15551110001` | `+15559999999` | `Hello` | (missing) | 404 / 404 | `{"error":{"code":"unknown_to","message":"No tenant uses that number."}}` | nothing | none | 0 | PASS |
| to-very-long | `SM1000` | `+15551110001` | `+1+1+1+1+1+1+1+1+1+1... (40 chars)` | `Hello` | valid (acme) | 404 / 404 | `{"error":{"code":"unknown_to","message":"No tenant uses that number."}}` | nothing | none | 0 | PASS |
| to-control-character | `SM1000` | `+15551110001` | `+1555\n` | `Hello` | valid (acme) | 404 / 404 | `{"error":{"code":"unknown_to","message":"No tenant uses that number."}}` | nothing | none | 0 | PASS |
| Error does not repea... (42 chars) | `SM1000` | `+15557654321` | `+15559999999` | `Hello` | valid (acme) | 404 / 404 | `{"error":{"code":"unknown_to","message":"No tenant uses that number."}}` | nothing | none | 0 | PASS |

### 6. Bad signatures (15 of 15 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Control: same reques... (40 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| signature-missing | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | (missing) | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| signature-empty | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | (empty) | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| signature-wrong | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | `00000000000000000000... (64 chars)` | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| signature-too-short | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | `f3814f4f836f1a38c059541216401a80` | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| signature-not-hex | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | `zzzzzzzzzzzzzzzzzzzz... (64 chars)` | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| signature-uppercase | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | `F3814F4F836F1A38C059... (64 chars)` | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| signature-non-ascii | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | `b'\xff\xfe'` | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| signature-other-tenant | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (baker) | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| signature-for-other-body | `SM1000` | `+15551110001` | `+15550000001` | `Tampered` | `f3814f4f836f1a38c059... (64 chars)` | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| bad-sid-unsigned | `SM 1` | `+15551110001` | `+15550000001` | `Hello` | (missing) | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| forged-stop-unsigned | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | (missing) | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| forged-stop-wrong | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | `00000000000000000000... (64 chars)` | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| forged-stop-other-tenant | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | valid (baker) | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |
| Missing and wrong si... (67 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | `00000000000000000000... (64 chars)` | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | nothing | none | 0 | PASS |

### 7. Unusual but valid input (14 of 14 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sid-at-max-length | `SSSSSSSSSSSSSSSSSSSS... (255 chars)` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| sid-with-dash-and-underscore | `SM_a-1` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| sid-with-dot | `SM.0001` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| sid-with-colon | `msg:abc` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| sid-non-ascii | `SMé1` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| very-long-sender | `SM1000` | `+1+1+1+1+1+1+1+1+1+1... (40 chars)` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=None, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| sender-with-control-character | `SM1000` | `+1555\x00` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=None, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| empty-message-body | `SM1000` | `+15551110001` | `+15550000001` | (empty) | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| short-code-sender | `SM1000` | `12345` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=None, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| unknown-sender-text | `SM1000` | `unknown` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=None, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| non-ascii-message-body | `SM1000` | `+15551110001` | `+15550000001` | `Héllo ✓` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| extra-field-is-ignored | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| percent-20-for-space | `SM1000` | `+15551110001` | `+15550000001` | `a b` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| lowercase-percent-encoding | `SM1000` | `+15551110001` | `+15550000001` | `Hi` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |

### 8. Duplicates (6 of 6 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Same delivery twice (2 deliveries) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Repeat with a differ... (59 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Second` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Repeat with a bad si... (42 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | `00000000000000000000... (64 chars)` | 403 / 403 | `{"error":{"code":"invalid_signature","message":"The signature is not valid."}}` | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Same MessageSid in t... (45 chars) | `SM1000` | `+15551110001` | `+15550000002` | `Hello` | valid (baker) | 200 / 200 | (empty) | 2 row(s); last: claimant=C-200, category=other, needs_review=False, dnc=False | none | 2 | PASS |
| Two simultaneous del... (42 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Two simultaneous STO... (37 chars) | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |

### 9. STOP and dnc (25 of 25 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Keyword 'STOP' | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Keyword 'stop' | `SM1000` | `+15551110001` | `+15550000001` | `stop` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Keyword 'Stop' | `SM1000` | `+15551110001` | `+15550000001` | `Stop` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Keyword 'STOPALL' | `SM1000` | `+15551110001` | `+15550000001` | `STOPALL` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Keyword 'stopall' | `SM1000` | `+15551110001` | `+15550000001` | `stopall` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Keyword 'UNSUBSCRIBE' | `SM1000` | `+15551110001` | `+15550000001` | `UNSUBSCRIBE` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Keyword 'unsubscribe' | `SM1000` | `+15551110001` | `+15550000001` | `unsubscribe` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Keyword '  Unsubscribe  ' | `SM1000` | `+15551110001` | `+15550000001` | `  Unsubscribe  ` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Keyword 'STOP\n' | `SM1000` | `+15551110001` | `+15550000001` | `STOP\n` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Keyword '\tstop ' | `SM1000` | `+15551110001` | `+15550000001` | `\tstop ` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| STOP with a dotted MessageSid | `SM.0001` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| STOP with a colon in MessageSid | `msg:abc` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| STOP with a 65-chara... (35 chars) | `SSSSSSSSSSSSSSSSSSSS... (65 chars)` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Opt-out fails, so th... (44 chars) | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 500 / 500 | `Internal Server Error` | nothing | none | 0 | PASS |
| Retry after a failed... (52 chars) | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| STOP from an unmatched number | `SM1000` | `+15559999999` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=None, category=None, needs_review=False, dnc=True | none | 0 | PASS |
| Repeat STOP (2 deliveries) | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| Later message after ... (42 chars) | `SM2` | `+15551110001` | `+15550000001` | `Thanks` | valid (acme) | 200 / 200 | (empty) | 2 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=True | C-100 | 1 | PASS |
| Earlier message show... (59 chars) | `GET /tenants/acme-law/messages` |  |  |  |  | 200 / 200 | `[{"message_sid":"SM1","claimant_id":"C-100","body":"Hello","category":"other","n...` | 2 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 1 | PASS |
| Not a keyword: 'STOP please' | `SM1000` | `+15551110001` | `+15550000001` | `STOP please` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Not a keyword: "don't stop" | `SM1000` | `+15551110001` | `+15550000001` | `don't stop` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Not a keyword: 'stop!' | `SM1000` | `+15551110001` | `+15550000001` | `stop!` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Not a keyword: 'STOP STOP' | `SM1000` | `+15551110001` | `+15550000001` | `STOP STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Not a keyword: 'S TOP' | `SM1000` | `+15551110001` | `+15550000001` | `S TOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Not a keyword: 'unsubscribed' | `SM1000` | `+15551110001` | `+15550000001` | `unsubscribed` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |

### 10. Classifier failures (14 of 14 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Answer 'banana' | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=True, dnc=False | none | 1 | PASS |
| Answer '' | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=True, dnc=False | none | 1 | PASS |
| Answer 'Status_Question' | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=True, dnc=False | none | 1 | PASS |
| Answer ' other' | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=True, dnc=False | none | 1 | PASS |
| Answer None | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=True, dnc=False | none | 1 | PASS |
| Answer 42 | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=True, dnc=False | none | 1 | PASS |
| Answer ['other'] | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=True, dnc=False | none | 1 | PASS |
| Answer {'category': 'other'} | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=True, dnc=False | none | 1 | PASS |
| Classifier raises an error | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=True, dnc=False | none | 1 | PASS |
| Valid answer 'status_question' | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=status_question, needs_review=False, dnc=False | none | 1 | PASS |
| Valid answer 'document_upload' | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=document_upload, needs_review=False, dnc=False | none | 1 | PASS |
| Valid answer 'schedule_call' | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=schedule_call, needs_review=False, dnc=False | none | 1 | PASS |
| Valid answer 'other' | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Classifier receives ... (38 chars) | `SM1000` | `+15551110001` | `+15550000001` | `When is my hearing?` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=status_question, needs_review=False, dnc=False | none | 1 | PASS |

### 11. Tenant isolation (7 of 7 passed)

| Case | MessageSid | From | To | Body | X-Signature | Status | Response body | Stored | Opted out | Calls | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Shared phone matches... (36 chars) | `SM1000` | `+15551110001` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Shared phone matches... (37 chars) | `SM1000` | `+15551110001` | `+15550000002` | `Hello` | valid (baker) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-200, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| Number known only to... (40 chars) | `SM1000` | `+15551110003` | `+15550000001` | `Hello` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=None, category=other, needs_review=False, dnc=False | none | 1 | PASS |
| STOP to acme opts out only C-100 | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-100, category=None, needs_review=False, dnc=True | C-100 | 0 | PASS |
| STOP to baker opts out only C-200 | `SM1000` | `+15551110001` | `+15550000002` | `STOP` | valid (baker) | 200 / 200 | (empty) | 1 row(s); last: claimant=C-200, category=None, needs_review=False, dnc=True | C-200 | 0 | PASS |
| dnc does not cross t... (62 chars) | `SM1000` | `+15551110001` | `+15550000001` | `STOP` | valid (acme) | 200 / 200 | (empty) | 2 row(s); last: claimant=C-200, category=other, needs_review=False, dnc=False | C-100 | 1 | PASS |
| GET shows only that ... (37 chars) | `GET /tenants/acme-law/messages` |  |  |  |  | 200 / 200 | `[]` | 1 row(s); last: claimant=C-200, category=other, needs_review=False, dnc=False | none | 1 | PASS |

## What this report does not cover

- **Real server:** cases run through FastAPI's test client, not over a network.
- **Load:** the simultaneous cases use two deliveries, not sustained traffic.
- **Crash recovery:** a process dying mid-request isn't simulated here. The rollback of a failed
  opt-out is covered in `tests/test_stop.py`.
- **Race strength:** the simultaneous cases show the current code behaves correctly. The review
  found this kind of test doesn't reliably catch a select-then-insert regression.

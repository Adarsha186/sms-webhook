import os
from contextlib import closing
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.classifier import KeywordClassifier
from app.db import connect, get_tenant, get_tenant_by_number, init_db, list_messages
from app.ingest import process_sms
from app.security import (
    MAX_BODY_BYTES,
    InvalidRequest,
    parse_form,
    validate_message_sid,
    verify_signature,
)


def create_app(db_path: str, classifier) -> FastAPI:
    init_db(db_path)
    app = FastAPI()

    @app.exception_handler(InvalidRequest)
    def reject(request: Request, error: InvalidRequest) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": error.message}},
        )

    def handle_sms(raw: bytes, signature: Optional[str]) -> Response:
        form = parse_form(raw)
        with closing(connect(db_path)) as conn:
            tenant = get_tenant_by_number(conn, form["To"])
        if tenant is None:
            raise InvalidRequest(404, "unknown_to", "No tenant uses that number.")
        if not verify_signature(raw, tenant["secret"], signature):
            raise InvalidRequest(403, "invalid_signature", "The signature is not valid.")
        validate_message_sid(form["MessageSid"])
        process_sms(db_path, classifier, tenant["id"], form)
        return Response(status_code=200)

    @app.post("/webhooks/sms")
    async def receive_sms(request: Request) -> Response:
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise InvalidRequest(413, "request_too_large", "The body is too large.")
        signature = request.headers.get("X-Signature")
        return await run_in_threadpool(handle_sms, raw, signature)

    @app.get("/tenants/{tenant}/messages")
    def get_messages(tenant: str):
        with closing(connect(db_path)) as conn:
            if get_tenant(conn, tenant) is None:
                raise InvalidRequest(404, "unknown_tenant", "No such tenant.")
            return list_messages(conn, tenant)

    return app


app = create_app(os.environ.get("SMS_DB_PATH", "sms.db"), KeywordClassifier())

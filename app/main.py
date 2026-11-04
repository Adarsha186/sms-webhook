import os
from contextlib import closing
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.classifier import KeywordClassifier
from app.db import connect, get_tenant_by_number, init_db, list_messages
from app.ingest import process_sms
from app.security import parse_form, verify_signature


def create_app(db_path: str, classifier) -> FastAPI:
    init_db(db_path)
    app = FastAPI()

    def handle_sms(raw: bytes, signature: Optional[str]) -> Response:
        form = parse_form(raw)
        with closing(connect(db_path)) as conn:
            tenant = get_tenant_by_number(conn, form["To"])
        if not verify_signature(raw, tenant["secret"], signature):
            return Response(status_code=403)
        process_sms(db_path, classifier, tenant["id"], form)
        return Response(status_code=200)

    @app.post("/webhooks/sms")
    async def receive_sms(request: Request) -> Response:
        raw = await request.body()
        signature = request.headers.get("X-Signature")
        return await run_in_threadpool(handle_sms, raw, signature)

    @app.get("/tenants/{tenant}/messages")
    def get_messages(tenant: str):
        with closing(connect(db_path)) as conn:
            return list_messages(conn, tenant)

    return app


app = create_app(os.environ.get("SMS_DB_PATH", "sms.db"), KeywordClassifier())

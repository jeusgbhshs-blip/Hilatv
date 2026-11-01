"""Bound upload ingress before multipart parsing can spool an unlimited body."""

from __future__ import annotations

import os

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from workers.assets import store

# A bounded allowance for multipart boundaries, headers and the kind field.
MULTIPART_OVERHEAD = 64 * 1024


class UploadLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = scope.get("path")
        if path == "/v1/assets":
            file_limit = store.MAX_BYTES
        elif path == "/v1/uploads":
            try:
                file_limit = max(
                    1, int(os.getenv("HILATV_UPLOAD_MAX_BYTES", "") or 8 * 1024 * 1024)
                )
            except ValueError:
                file_limit = 8 * 1024 * 1024
        else:
            await self.app(scope, receive, send)
            return
        limit = file_limit + MULTIPART_OVERHEAD
        lengths = [
            value for key, value in scope.get("headers", []) if key.lower() == b"content-length"
        ]
        if lengths:
            try:
                if len(lengths) != 1 or int(lengths[0]) < 0:
                    raise ValueError("invalid content length")
                declared = int(lengths[0])
            except ValueError:
                await JSONResponse({"detail": "上传长度无效"}, status_code=400)(
                    scope, receive, send
                )
                return
            if declared > limit:
                await JSONResponse({"detail": "文件过大"}, status_code=413)(scope, receive, send)
                return
        consumed = 0

        async def bounded_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    # Starlette's multipart parser closes spooled files on a
                    # stream exception. FastAPI preserves this HTTP status.
                    raise HTTPException(status_code=413, detail="文件过大")
            return message

        await self.app(scope, bounded_receive, send)

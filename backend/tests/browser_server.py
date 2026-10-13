"""Disposable browser-test server. Never uses the operator's data directory."""

from pathlib import Path
import os
import tempfile

import uvicorn
from fastapi import HTTPException, Request

from app.api import create_app
from app.auth import authenticate, create_user
from app.api import COOKIE
from app.input_models import UserCreate


if __name__ == "__main__":
    os.environ["KDOG_GEMINI_MODEL"] = "gemini-test-only"
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="kdog-browser-") as directory:
        app = create_app(Path(directory) / "data", public_origin="http://127.0.0.1:8765")
        with app.state.store.connect(write=True) as db:
            for role in ("operator", "reviewer", "developer", "admin"):
                create_user(db, UserCreate(username=role, password="Browser-test-only-42", role=role))

        @app.post("/api/test-fixtures/gemini-fallback/{action}")
        def gemini_fixture(action: str, request: Request):
            store = app.state.store
            with store.connect() as db:
                actor = authenticate(db, request.cookies.get(COOKIE))
                if actor["role"] != "developer":
                    raise HTTPException(403, "합성 fixture는 개발자 시험 계정만 만들 수 있습니다.")
            from tests.browser_gemini_fixture import BrowserGeminiFixture
            if action not in ("seed", "advance"):
                raise HTTPException(404, "없는 합성 fixture 작업입니다.")
            if app.state.gemini_fixture is None:
                app.state.gemini_fixture = BrowserGeminiFixture(store)
            return app.state.gemini_fixture.advance() if action == "advance" else app.state.gemini_fixture.state()

        # The product's API/SPA fallback routes precede appended test routes.
        app.router.routes.insert(0, app.router.routes.pop())
        app.state.gemini_fixture = None
        # Only the explicit synthetic fixture invokes a Worker with a fake transport.
        try:
            uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)
        finally:
            if app.state.gemini_fixture:
                app.state.gemini_fixture.close()

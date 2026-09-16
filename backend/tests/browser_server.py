"""Disposable browser-test server. Never uses the operator's data directory."""

from pathlib import Path
import os
import tempfile

import uvicorn

from app.api import create_app
from app.auth import create_user
from app.input_models import UserCreate


if __name__ == "__main__":
    os.environ["KDOG_GEMINI_MODEL"] = "gemini-test-only"
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="kdog-browser-") as directory:
        app = create_app(Path(directory), public_origin="http://127.0.0.1:8765")
        with app.state.store.connect(write=True) as db:
            for role in ("operator", "reviewer", "developer", "admin"):
                create_user(db, UserCreate(username=role, password="Browser-test-only-42", role=role))
        # The 55-item analysis pipeline is frozen, so no worker runs here; intake screens are what the specs exercise.
        uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)

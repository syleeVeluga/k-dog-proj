"""Disposable browser-test server. Never uses the operator's data directory."""

from pathlib import Path
import os
import tempfile
import threading

import uvicorn

from app.api import create_app
from app.auth import create_user
from app.input_models import UserCreate
from app.worker import Worker
from tests.evaluation_fixtures import FakeEvaluator
from tests.test_observation import FakeObserver, fake_probe


if __name__ == "__main__":
    os.environ["KDOG_GEMINI_MODEL"] = "gemini-test-only"
    os.environ.pop("GEMINI_API_KEY", None)
    with tempfile.TemporaryDirectory(prefix="kdog-browser-") as directory:
        app = create_app(Path(directory), public_origin="http://127.0.0.1:8765")
        with app.state.store.connect(write=True) as db:
            for role in ("operator", "reviewer", "developer", "admin"):
                create_user(db, UserCreate(username=role, password="Browser-test-only-42", role=role))
        stop = threading.Event()
        worker = Worker(app.state.store, observer=FakeObserver(), evaluator=FakeEvaluator(), probe=fake_probe)

        def process_fixtures():
            while not stop.wait(0.1):
                worker.once()

        thread = threading.Thread(target=process_fixtures, daemon=True)
        thread.start()
        try:
            uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)
        finally:
            stop.set()
            thread.join(timeout=5)

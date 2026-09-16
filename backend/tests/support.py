"""Shared API test harness: a throwaway data folder, one account per role, synthetic bytes only."""

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.auth import create_user
from app.domain.catalog import SURVEY_IDS
from app.input_models import UserCreate

PASSWORD = "Synthetic-test-only-42"
ORIGIN = "http://127.0.0.1:8000"
ROLES = ("operator", "reviewer", "admin", "developer")


class AppCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kdog-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.store = self.app.state.store
        with self.store.connect(write=True) as db:
            for role in ROLES:
                create_user(db, UserCreate(username=role, password=PASSWORD, role=role))
        self.client = self.client_for("operator")
        self.version = self.client.get("/api/catalog/survey").json()["version"]

    def client_for(self, role=None):
        client = TestClient(self.app, base_url=ORIGIN, headers={"X-KDOG-Request": "1"})
        self.addCleanup(client.close)
        if role:
            result = client.post("/api/auth/login", json={"username": role, "password": PASSWORD})
            self.assertEqual(result.status_code, 200, result.text)
        return client

    def login(self, role):
        self.assertEqual(self.client.post("/api/auth/login", json={"username": role, "password": PASSWORD}).status_code, 200)

    def make_case(self, participant_id="0001", event_id="TEST", dog_name="가상견"):
        response = self.client.post("/api/cases", json={"participant_id": participant_id, "event_id": event_id, "dog_name": dog_name})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def get_case(self, item):
        return self.client.get(f"/api/cases/{item['case_id']}").json()

    def delete_case(self, item):
        response = self.client.post(f"/api/cases/{item['case_id']}/deletion", json={"expected_revision": item["input_revision"]})
        self.assertEqual(response.status_code, 200, response.text)

    def upload(self, item, data=b"synthetic-video-one", name="source.mp4"):
        return self.client.post(f"/api/cases/{item['case_id']}/videos", content=data, params={
            "session_id": item["selected_session_id"], "filename": name,
            "expected_revision": item["input_revision"]})

    def answers(self, item, value=3, not_applicable=()):
        return {"expected_revision": item["input_revision"], "session_id": item["selected_session_id"],
                "survey_version": self.version, "not_applicable": list(not_applicable),
                "answers": {item_id: (None if item_id in not_applicable else value) for item_id in SURVEY_IDS}}

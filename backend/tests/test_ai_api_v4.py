import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.auth import password_hash
from app.usage import summarize
from app.worker import Worker
from tests import test_run_v4 as support
from tests.support import ORIGIN, PASSWORD


class AiApiV4Tests(unittest.TestCase):
    def setUp(self):
        self.helper = support.RunV4Tests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.store = self.helper.store
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET password_hash=?", (password_hash(PASSWORD),))
        self.app = create_app(self.store.root)
        self.clients = {}
        for role in ("operator", "reviewer", "developer"):
            client = TestClient(self.app, base_url=ORIGIN, headers={"X-KDOG-Request": "1"})
            self.addCleanup(client.close)
            self.assertEqual(client.post("/api/auth/login", json={"username": role, "password": PASSWORD}).status_code, 200)
            self.clients[role] = client
        self.operator, self.developer = self.clients["operator"], self.clients["developer"]
        self.path = f"/api/cases/{self.helper.case_id}/sessions/{self.helper.session_id}/runs-s1"

    def activate(self):
        state = self.developer.get("/api/settings-s1")
        self.assertEqual(state.status_code, 200, state.text)
        config = state.json()["config"]
        config["raw_observation_scope_confirmed"] = True
        saved = self.developer.post("/api/settings-s1", json={"expected_active": "inactive", "config": config})
        self.assertEqual(saved.status_code, 201, saved.text)
        version = saved.json()["version"]
        result = self.developer.post(f"/api/settings-s1/{version}/activate", json={"expected_active": "inactive"})
        self.assertEqual(result.status_code, 200, result.text)
        return version

    def test_settings_contract_permissions_conflict_and_no_provider_schema_validation(self):
        for role in ("operator", "reviewer"):
            self.assertEqual(self.clients[role].get("/api/settings-s1").status_code, 403)
        version = self.activate()
        diff = self.developer.get(f"/api/settings-s1/{version}/diff")
        self.assertEqual(diff.status_code, 200, diff.text)
        state = self.developer.get("/api/settings-s1").json()
        group = next(iter(state["groups"]))
        checked = self.developer.post(f"/api/settings-s1/{version}/validate-s1", json={"group": group, "mode": "schema"})
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertEqual(checked.json()["usage"]["provider_calls"], 0)
        self.assertEqual(self.developer.post(f"/api/settings-s1/{version}/validate-s1", json={"group": group, "mode": "provider"}).status_code, 422)
        self.assertEqual(self.developer.post(f"/api/settings-s1/{version}/activate", json={"expected_active": "inactive"}).status_code, 409)
        ready = self.operator.get("/api/scoring-ai-s1/readiness").json()
        self.assertEqual((ready["enabled"], ready["planned_provider_calls"], ready["judgement_status"]), (True, 42, "policy_pending_D04"))
        self.assertEqual(self.operator.get(self.path).json(), [])

    def test_explicit_run_stop_retry_public_status_and_s1_usage_include_only_reserved_calls(self):
        self.activate()
        request = self.helper.request.model_dump(mode="json")
        self.assertEqual(self.clients["reviewer"].post(self.path, json=request).status_code, 403)
        started = self.operator.post(self.path, json=request)
        self.assertEqual(started.status_code, 201, started.text)
        run_id = started.json()["run_id"]
        self.assertEqual(self.operator.post(self.path, json=request).json()["run_id"], run_id)
        url = f"/api/runs-s1/{run_id}"
        stopped = self.operator.post(url + "/stop", json={"expected_updated_at": started.json()["updated_at"], "reason": "synthetic explicit stop"})
        self.assertEqual(stopped.status_code, 200, stopped.text)
        retried = self.operator.post(url + "/retry", json={"expected_updated_at": stopped.json()["updated_at"], "reason": "synthetic explicit retry"})
        self.assertEqual(retried.status_code, 200, retried.text)
        calls = []

        class FakeProvider:
            def request_v4(self, files, config, context, schema, guard):
                guard()
                calls.append(context)
                return {**context["identity"], "observations": [{"code": item["code"], "value": None,
                    "status": "unobserved", "reason": "synthetic unobserved"} for item in context["items"]]}, {
                    "provider_usage": {"total_input_tokens": 10, "total_output_tokens": 5, "total_tokens": 15}}

        Worker(self.store, observer=FakeProvider()).once()
        response = self.clients["reviewer"].get(url)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual((result["status"], result["reserved_calls"], len(calls)), ("succeeded", 42, 42))
        self.assertTrue(result["result_available"])
        self.assertEqual(result["steps"][0]["total_tokens"], 15)
        for private in ("prompt", "response_schema", "observations", "output_ref", "credential_reference"):
            self.assertNotIn(private, response.text)
        usage = summarize(self.store)
        self.assertEqual(usage["calls_reserved"], 42)
        self.assertEqual(usage["unpriced_or_uncertain_calls"], 42)
        self.assertIsNone(usage["complete_meter_cost_estimate"])
        self.assertEqual(usage["groups"][0]["provider"], "gemini")
        self.assertEqual(usage["groups"][0]["model"], "gemini-3.8-flash")
        self.assertEqual(self.developer.get(url).status_code, 403)
        self.assertEqual(len(self.operator.get(self.path).json()), 1)

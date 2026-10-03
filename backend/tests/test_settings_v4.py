import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from app import scoring_ai_v4, settings_v4 as settings
from app.storage import Store


class SettingsV4Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kdog-settings-s1-")
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        with self.store.connect(write=True) as db:
            for name in ("developer", "operator"):
                db.execute("INSERT INTO users(username,role,password_hash) VALUES(?,?,?)", (name, name, "synthetic-no-login"))

    def draft(self, **updates):
        config = settings.defaults().model_dump(mode="json")
        config.update(updates)
        return settings.save(self.store, settings.AiDraftV4.model_validate_json(json.dumps({"expected_active": "inactive", "config": config})), "developer")["version"]

    def test_exact_source_groups_and_default_sampling_do_not_enable_ai_or_d04(self):
        result = settings.view(self.store)
        self.assertEqual((result["active_version"], result["planned_provider_calls"], len(result["groups"])), ("inactive", 42, 43))
        self.assertEqual(sum(len(group["codes"]) for group in result["groups"].values()), 86)
        self.assertEqual(result["judgement_status"], "policy_pending_D04")
        self.assertEqual(result["provider_trial_status"], "deferred_S16")
        self.assertIsNone(result["price_estimate"])
        self.assertFalse(result["config"]["raw_observation_scope_confirmed"])
        self.assertTrue(all(stage["fps"] == 1 and stage["input_variant"] == "ai" for stage in result["config"]["groups"].values()))

    def test_draft_activation_conflict_hash_pin_and_immutable_history(self):
        version = self.draft(raw_observation_scope_confirmed=True)
        self.assertIn("raw_observation_scope_confirmed", settings.difference(self.store, version)["diff"])
        settings.activate(self.store, version, settings.AiActivateV4(expected_active="inactive"), "developer")
        self.assertEqual(settings.view(self.store)["active_version"], version)
        with self.assertRaises(HTTPException) as caught:
            self.draft()
        self.assertEqual(caught.exception.status_code, 409)
        with self.store.connect() as db:
            detail = json.loads(db.execute("SELECT detail_json FROM changes WHERE target=? AND action='settings_v4.draft'", (version,)).fetchone()[0])
        path = self.store.path(detail["ref"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), detail["hash"])
        path.write_bytes(path.read_bytes().replace(b'"max_ai_calls":100', b'"max_ai_calls":101'))
        with self.assertRaises(HTTPException) as caught:
            settings.view(self.store)
        self.assertEqual(caught.exception.status_code, 409)

    def test_activation_requires_raw_scope_and_dynamic_call_budget(self):
        for changes in ({}, {"raw_observation_scope_confirmed": True, "max_ai_calls": 41}):
            version = self.draft(**changes)
            with self.assertRaises(HTTPException) as caught:
                settings.activate(self.store, version, settings.AiActivateV4(expected_active="inactive"), "developer")
            self.assertEqual(caught.exception.status_code, 422)

    def test_caps_schema_contract_and_developer_revocation(self):
        for update in ({"max_attempts": 4}, {"max_schema_repairs": 2}, {"max_ai_calls": 0}, {"groups": {}}):
            with self.assertRaises(ValidationError):
                settings.AiPipelineV4.model_validate({**settings.defaults().model_dump(), **update})
        for update in ({"fps": 8.0}, {"processing_mode": "agentic", "fps": 1.0}, {"fps": None}, {"model": "old-model"}):
            with self.assertRaises(ValidationError):
                settings.AiStageConfigV4(prompt="synthetic", **update)
        version = self.draft(raw_observation_scope_confirmed=True)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='developer'")
        for actor in ("developer", "operator"):
            with self.assertRaises(HTTPException) as caught:
                settings.activate(self.store, version, settings.AiActivateV4(expected_active="inactive"), actor)
            self.assertEqual(caught.exception.status_code, 403)

    def test_schema_trial_is_synthetic_only_and_keeps_legacy_settings_inactive(self):
        with self.store.connect(write=True) as db:
            self.store.audit(db, "developer", "old", "settings_v3.activate", {"version": "old"})
        self.assertEqual(settings.view(self.store)["active_version"], "inactive")
        version = self.draft()
        selected = next(iter(settings.groups()))
        result = settings.trial(self.store, version, settings.AiTrialV4(group=selected), "developer")
        self.assertEqual(result["usage"]["provider_calls"], 0)
        self.assertTrue(all(row["value"] is None for row in result["output"]["observations"]))
        self.assertEqual(len(settings.view(self.store)["trials"]), 1)
        with self.assertRaises(ValidationError):
            settings.AiTrialV4(group=selected, mode="provider")

    def test_original_sampling_and_execution_version_pin(self):
        pipeline = settings.defaults()
        key = next(iter(pipeline.groups))
        pipeline.groups[key] = settings.AiStageConfigV4(prompt="synthetic original", input_variant="original", fps=8.0)
        config = scoring_ai_v4.configuration("pinned-s1-version", pipeline)
        self.assertEqual(config.stages[0].production_fps, "source_frames")
        self.assertEqual(config.stages[0].request_fps, 8.0)
        self.assertEqual(config.active_settings_version, "pinned-s1-version")
        self.assertEqual(len(config.stages), 45)
        self.assertEqual(sum(stage.provider_call for stage in config.stages), 42)


if __name__ == "__main__":
    unittest.main()

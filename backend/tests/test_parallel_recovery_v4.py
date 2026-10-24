"""Real child termination and mixed credential outcomes, using synthetic bytes."""
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from fastapi import HTTPException

from app import analysis, maintenance, run_v4, scoring_ai_v4, secrets, settings_v4
from app.gemini import ProviderError
from app.gemini_v4 import GeminiScorerV4
from app.storage import Store
from app.worker import Worker
from tests import test_run_v4 as fixtures
from tests.test_gemini_key_fallback import BACKUP, PRIMARY, SyntheticGemini


CHILD = r'''
from pathlib import Path
import sys, threading
from app import analysis
from app.storage import Store
from app.worker import Worker
store, markers, phase = Store(Path(sys.argv[1])), Path(sys.argv[2]), sys.argv[3]
worker = Worker(store)
def handler(snapshot, group, row):
    def work(step):
        worker.reserve_call(row, step)
        if phase == "artifact":
            analysis.write_output(store, row, step, {"synthetic": "valid", "usage": {}})
        else:
            with store.connect(write=True) as db:
                detail = {"upload_id": step["step_id"], "credential_reference": "synthetic-ref"}
                store.audit(db, "operator", row["run_id"], "remote.upload_started", detail)
                if phase == "inference":
                    store.audit(db, "operator", row["run_id"], "remote.uploaded", {**detail, "remote_file_name": "files/"+step["step_id"]})
        (markers/step["step_id"]).write_text(phase)
        threading.Event().wait(300)
        return {"synthetic": "valid", "usage": {}}
    return lambda value: value, work
worker.v4_work = handler
worker.once()
'''


class ParallelRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RunV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        snapshots = tempfile.TemporaryDirectory(prefix="kdog-pa05-snapshots-")
        self.addCleanup(snapshots.cleanup)
        self.snapshots = Path(snapshots.name)

    def config(self, n):
        pipeline = settings_v4.defaults()
        pipeline.raw_observation_scope_confirmed = True
        pipeline.max_parallel_score_groups = n
        config = scoring_ai_v4.configuration(None, pipeline)
        return config.model_copy(update={"stages": config.stages[:n]})

    def test_process_kill_at_upload_inference_and_complete_artifact_preserves_recovery(self):
        for phase in ("upload", "inference", "artifact"):
            with self.subTest(phase=phase):
                from app.storage import uid
                run_id = self.fixture.enqueue(config=self.config(2), value=self.fixture.request.model_copy(update={"request_id": uid()}))["run_id"]
                markers = self.store.root/phase
                markers.mkdir()
                child = subprocess.Popen([sys.executable, "-X", "utf8", "-c", CHILD, str(self.store.root), str(markers), phase],
                    cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    deadline = time.monotonic()+15
                    while len(list(markers.iterdir())) < 2:
                        self.assertIsNone(child.poll(), "synthetic child exited early")
                        if time.monotonic() >= deadline:
                            self.fail("child attempts did not reach the controlled boundary")
                        time.sleep(0.05)
                    with self.assertRaises(HTTPException):
                        Worker(self.store).once()
                finally:
                    child.kill()
                    child.wait(timeout=10)
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE runs SET lease_expires_at='2000-01-01T00:00:00Z' WHERE run_id=?", (run_id,))
                calls = []
                def handler(snapshot, group, row):
                    def work(step):
                        Worker(self.store).reserve_call(row, step)
                        calls.append(step["step_id"])
                        return {"synthetic": "valid", "usage": {}}
                    return lambda value: value, work
                Worker(self.store, v4_work=handler).once()
                self.assertEqual(self.fixture.row(run_id)["status"], "succeeded")
                self.assertEqual(len(calls), 0 if phase == "artifact" else 2)
                with self.store.connect() as db:
                    abandoned = db.execute("SELECT usage_json FROM steps WHERE run_id=? AND status='abandoned'", (run_id,)).fetchall()
                if phase != "artifact":
                    import json
                    self.assertEqual(len(abandoned), 2)
                    self.assertTrue(all(json.loads(step[0])["billing_uncertain"] for step in abandoned))
                before = self.fixture.row(run_id)["config_snapshot_json"]
                backup = self.snapshots/(phase+"-backup")
                restored_root = self.snapshots/(phase+"-restored")
                maintenance.backup(self.store, backup, "operator")
                maintenance.restore(self.store, backup, restored_root)
                with Store(restored_root).connect() as db:
                    self.assertEqual(db.execute("SELECT config_snapshot_json FROM runs WHERE run_id=?", (run_id,)).fetchone()[0], before)

    def test_primary_successes_survive_parallel_fallback_without_recall(self):
        config = self.config(4)
        run_id = self.fixture.enqueue(config=config)["run_id"]
        secrets.change(self.store, "gemini", PRIMARY, "developer")
        secrets.change(self.store, "gemini", BACKUP, "developer", slot="backup")
        transport, ready = SyntheticGemini(), threading.Barrier(4)
        transport.fail_primary = False
        first = config.stages[0].item_codes[0]
        seen = []
        def hook(key, context):
            seen.append((key, context["items"][0]["code"]))
            if key == PRIMARY:
                ready.wait(timeout=10)
                if context["items"][0]["code"] == first:
                    raise ProviderError("provider_http_503", http_status=503, retryable=True, uncertain=True)
        transport.hook = hook
        worker = Worker(self.store, observer=GeminiScorerV4(self.store, transport))
        worker.once()
        self.assertEqual(self.fixture.row(run_id)["status"], "retry_wait")
        self.fixture.due(run_id)
        worker.once()
        self.assertEqual(self.fixture.row(run_id)["status"], "succeeded")
        self.assertEqual(sum(key == PRIMARY for key, _ in seen), 4)
        self.assertEqual([(key, code) for key, code in seen if key == BACKUP], [(BACKUP, first)])
        self.assertFalse(any(step["remote_cleanup_pending"] for step in run_v4.view(self.store, run_id, self.fixture.user)["steps"]))

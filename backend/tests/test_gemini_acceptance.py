"""GK-T20: real assembly and immutable output/restore boundaries; synthetic REST only."""

import json
import tempfile
import unittest
from pathlib import Path

from app import maintenance, report_runs_v4 as reports, run_v4, secrets
from app.gemini_v4 import GeminiScorerV4
from app.storage import Store, uid
from app.worker import Worker
from tests.browser_gemini_fixture import BrowserGeminiFixture, response
from tests.test_gemini_key_fallback import BACKUP, PRIMARY, SyntheticGemini
from tests.test_opinions_v4 import model


class GeminiAcceptanceTests(unittest.TestCase):
    def test_real_assembly_reuse_restore_and_reregistration_preserve_outputs(self):
        with tempfile.TemporaryDirectory(prefix="kdog-gk04-") as temporary:
            root = Path(temporary)
            store = Store(root / "data")
            fixture = BrowserGeminiFixture(store)
            self.addCleanup(fixture.close)
            fixture.advance(); fixture.advance()
            case_id, session_id, user = fixture.helper.case_id, fixture.helper.session_id, fixture.user
            score = run_v4.view(store, fixture.score["run_id"], user)
            report_id = fixture.report["run_id"]
            report = reports.view(store, report_id, user)
            self.assertEqual((score["status"], score["reserved_calls"], score["credential_slot"]), ("succeeded", 44, "backup"))
            self.assertEqual((report["status"], sum(step["provider_calls"] for step in report["steps"]), report["credential_slot"]), ("succeeded", 2, "backup"))
            attempts = [step for step in report["steps"] if step["provider_calls"]]
            self.assertEqual([step["credential_slot"] for step in attempts], ["primary", "backup"])
            self.assertTrue(attempts[0]["billing_uncertain"])
            self.assertTrue(any(step["remote_cleanup_pending"] for step in score["steps"]))

            outputs = {kind: reports.download(store, case_id, session_id, report_id, kind, user)[0]
                       for kind in ("html", "pdf", "manifest")}
            self.assertIn("관찰".encode(), outputs["html"])
            self.assertTrue(outputs["pdf"].startswith(b"%PDF-"))
            publication = json.loads(outputs["manifest"])
            self.assertEqual(publication["final"]["hash"], report["final"]["hash"])
            with store.connect() as db:
                refs = [row[0] for row in db.execute("SELECT manifest_ref FROM basic_results")]
            refs.append(publication["final"]["ref"])
            pinned = {ref: store.path(ref).read_bytes() for ref in refs}
            call_count = len(fixture.transport.calls)
            request = model(reports.ReportStartV4, expected_revision=fixture.helper.current()["input_revision"],
                            request_id=uid(), final=report["final"], reuse_run_id=report_id)
            reused = reports.enqueue(store, case_id, session_id, request, user)
            self.assertTrue(fixture.worker.once())
            reused_view = reports.view(store, reused["run_id"], user)
            self.assertEqual((reused_view["status"], sum(step["provider_calls"] for step in reused_view["steps"]), reused_view["credential_slot"]), ("succeeded", 0, None))
            self.assertEqual(reused_view["steps"][0]["source_credential_slot"], "backup")
            self.assertEqual(len(fixture.transport.calls), call_count)
            for kind, content in outputs.items():
                self.assertEqual(reports.download(store, case_id, session_id, report_id, kind, user)[0], content)

            with store.connect(write=True) as db:
                db.execute("UPDATE users SET session_hash=?,session_expires='2099-01-01T00:00:00Z' WHERE username=?", ("a" * 64, user.username))
                changes = [tuple(row) for row in db.execute("SELECT * FROM changes ORDER BY change_id")]
            backup = root / "backup"
            maintenance.backup(store, backup, user.username)
            self.assertFalse((backup / "secrets").exists())
            for file in backup.rglob("*"):
                if file.is_file():
                    self.assertNotIn(PRIMARY.encode(), file.read_bytes())
                    self.assertNotIn(BACKUP.encode(), file.read_bytes())
            maintenance.restore(store, backup, root / "restored")
            restored = Store(root / "restored")
            with restored.connect() as db:
                self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM changes ORDER BY change_id")], changes)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE session_hash IS NOT NULL OR session_expires IS NOT NULL").fetchone()[0], 0)
            self.assertTrue(all(not slot["available"] for slot in secrets.slot_states(restored)))
            for kind, content in outputs.items():
                self.assertEqual(reports.download(restored, case_id, session_id, report_id, kind, user)[0], content)
            transport = SyntheticGemini(response)
            worker = Worker(restored, observer=GeminiScorerV4(restored, transport))
            fresh_request = request.model_copy(update={"request_id": uid(), "reuse_run_id": None})
            missing = reports.enqueue(restored, case_id, session_id, fresh_request, user)
            self.assertTrue(worker.once())
            self.assertNotEqual(reports.view(restored, missing["run_id"], user)["status"], "succeeded")
            self.assertEqual(transport.calls, [])
            secrets.change(restored, "gemini", PRIMARY, "developer")
            secrets.change(restored, "gemini", BACKUP, "developer", slot="backup")
            new = reports.enqueue(restored, case_id, session_id, fresh_request.model_copy(update={"request_id": uid()}), user)
            self.assertTrue(worker.once())
            pending = reports.view(restored, new["run_id"], user)
            self.assertEqual((pending["status"], pending["steps"][0]["credential_slot"]), ("retry_wait", "primary"))
            with restored.connect(write=True) as db:
                db.execute("UPDATE steps SET retry_at='2000-01-01T00:00:00Z' WHERE run_id=?", (new["run_id"],))
            self.assertTrue(worker.once())
            complete = reports.view(restored, new["run_id"], user)
            self.assertEqual((complete["status"], sum(step["provider_calls"] for step in complete["steps"]), complete["credential_slot"]), ("succeeded", 2, "backup"))
            maintenance.clean(restored)
            for kind, content in outputs.items():
                self.assertEqual(reports.download(restored, case_id, session_id, report_id, kind, user)[0], content)
            for ref, content in pinned.items():
                self.assertEqual(restored.path(ref).read_bytes(), content)
                self.assertEqual(store.path(ref).read_bytes(), content)


if __name__ == "__main__":
    unittest.main()

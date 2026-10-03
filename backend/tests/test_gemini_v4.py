"""HTTP transport fixtures only; no real provider or participant media."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app.gemini import ProviderError
from app.gemini_v4 import GeminiScorerV4
from app.reset_s1 import pending_remote_cleanup
from app.storage import Store


class GeminiTransportV4Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kdog-ai-transport-")
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name)/"data")
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO users(username,password_hash,role) VALUES ('synthetic','fixture','operator')")
        self.path = Path(temporary.name)/"synthetic.mp4"
        self.path.write_bytes(b"synthetic")
        self.calls = []
        self.mode = "success"
        self.processing = False
        key = patch("app.gemini_v4.credential", return_value=("synthetic-test-key","synthetic-ref"))
        key.start()
        self.addCleanup(key.stop)
        self.adapter = GeminiScorerV4(self.store, self.transport)
        self.config = {"model":"gemini-3.8-flash","prompt":"synthetic", "fps":1.0,"processing_mode":"static",
                       "media_resolution":"medium","max_output_tokens":4096,"thinking_level":"medium"}
        self.context = {"run_id":"run-synthetic","audit_actor":"synthetic"}

    def transport(self, method, url, key, **kwargs):
        self.calls.append((method,url,kwargs))
        if method == "DELETE":
            if self.mode == "delete_failure":
                raise ProviderError("transport",uncertain=True)
            return {},{}
        if url.endswith("/upload/v1beta/files"):
            return {},{"X-Goog-Upload-URL":"https://generativelanguage.googleapis.com/synthetic-upload"}
        if url.endswith("/synthetic-upload"):
            if self.mode == "lost_upload_response":
                raise ProviderError("transport",uncertain=True)
            return {"file":{"name":"files/synthetic","uri":"https://generativelanguage.googleapis.com/v1beta/files/synthetic",
                             "state":"PROCESSING" if self.processing else "ACTIVE"}},{}
        if method == "GET":
            return {"name":"files/synthetic","uri":"https://generativelanguage.googleapis.com/v1beta/files/synthetic","state":"ACTIVE"},{}
        text = "not-json" if self.mode == "invalid_json" else '{"observations":[]}'
        return {"status":"completed", "model":"gemini-3.8-flash", "id":"synthetic-result", "usage":{"total_tokens":9},
                "steps":[{"type":"model_output","content":[{"type":"text","text":text}]}]},{}

    def execute(self, guard=lambda: None):
        return self.adapter.request_v4([(self.path, SimpleNamespace(clip_id="clip-1",size_bytes=9))],self.config,
                                       self.context,{"type":"object"},guard)

    def test_stateless_interaction_clip_identity_and_cleanup_timing(self):
        self.processing = True
        with patch("app.gemini_v4.time.sleep"):
            raw,usage = self.execute()
        self.assertEqual(raw,{"observations":[]})
        self.assertFalse(usage["remote_cleanup_pending"])
        self.assertEqual(pending_remote_cleanup(self.store),[])
        body = next(options["data"] for method,url,options in self.calls if url.endswith("/interactions"))
        self.assertFalse(body["store"])
        self.assertEqual(body["input"][0]["text"],"다음 영상의 clip_id: clip-1")
        self.assertEqual(body["input"][1]["processing"],{"type":"static","fps":1.0})
        self.assertNotIn("name",body["input"][1])
        self.assertEqual(set(usage["timing"]),{"upload_seconds","processing_seconds","inference_seconds","cleanup_seconds"})

    def test_invalid_json_is_repairable_and_cleanup_still_runs(self):
        self.mode = "invalid_json"
        with self.assertRaises(ProviderError) as caught:
            self.execute()
        self.assertEqual(caught.exception.code,"v4_schema_invalid")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(pending_remote_cleanup(self.store),[])

    def test_lost_upload_and_failed_delete_have_durable_cleanup_obligations(self):
        self.mode = "delete_failure"
        _,usage = self.execute()
        self.assertTrue(usage["remote_cleanup_pending"])
        self.assertEqual(pending_remote_cleanup(self.store)[0]["status"],"delete_pending")
        self.mode = "lost_upload_response"
        with self.assertRaises(ProviderError):
            self.execute()
        self.assertEqual({item["status"] for item in pending_remote_cleanup(self.store)},
                         {"delete_pending","upload_response_unconfirmed"})

    def test_deletion_during_processing_blocks_inference_but_allows_cleanup(self):
        self.processing = True
        def guard():
            if any(url.endswith("/synthetic-upload") for _,url,_ in self.calls):
                raise HTTPException(410,"deleted")
        with self.assertRaises(HTTPException):
            self.execute(guard)
        self.assertFalse(any(url.endswith("/interactions") for _,url,_ in self.calls))
        self.assertEqual(pending_remote_cleanup(self.store),[])

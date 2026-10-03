import shutil
import unittest

from app.api import create_app
from app.domain.catalog_v4 import OPTIONAL_CODES, SEGMENTS, load_catalog_v4
from app.media import command
from tests.support import AppCase


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Synthetic FFmpeg media required")
class PreprocessApiV4Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.client = self.client_for("operator")

    def test_real_preprocess_receipt_roundtrip_clip_access_and_immutable_reuse(self):
        sample = self.root / "synthetic.mp4"
        command(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=4",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "2", "-c:v", "libx264", "-c:a", "aac", str(sample)])
        source = sample.read_bytes()
        item = self.make_case()
        base = f"/api/cases/{item['case_id']}/sessions/{item['selected_session_id']}"
        receipt = self.client.post("/api/uploads", json={"request_id": "sample", "filename": "sample.mp4", "expected_size": len(source)}).json()
        self.client.put(f"/api/uploads/{receipt['upload_id']}/content?request_id=sample", content=source)
        linked = self.client.post(f"/api/uploads/{receipt['upload_id']}/link", json={"case_id": item["case_id"],
            "session_id": item["selected_session_id"], "expected_revision": item["input_revision"], "camera_id": "CAM1"}).json()
        video_id = linked["video_id"]
        record = {"video_id": video_id, "procedure_edition": "s1_confirmed", "procedure_note": "합성 API 시험", "confirmed": True,
                  "segments": [{"segment": key, "video_id": video_id,
                    **({"start_sec": 0.0, "end_sec": 1.5} if key == "entry" else {"state": "not_performed", "reason": "합성 시험 생략"})}
                    for key, _, _ in SEGMENTS]}
        response = self.client.put(base + "/recording-s1", json={"expected_revision": linked["linked_revision"], "recording": record})
        self.assertEqual(response.status_code, 200, response.text)
        value = {"request_id": "batch", "expected_revision": response.json()["input_revision"], "camera_priority": ["CAM1"]}
        endpoint = base + "/preprocess-s1"
        self.assertTrue(self.client.get(endpoint).json()["ready"])
        self.assertEqual(self.client_for("reviewer").post(endpoint, json=value).status_code, 403)
        result = self.client.post(endpoint, json=value)
        self.assertEqual(result.status_code, 200, result.text)
        batch = result.json()
        self.assertEqual(batch["status"], "complete")
        repeated = self.client.post(endpoint, json=value)
        self.assertEqual(repeated.json()["batch_id"], batch["batch_id"])
        state = self.client.get(endpoint).json()
        reused = self.client.post(endpoint, json={**value, "request_id": "reuse", "reuse": state["result_pointer"]})
        self.assertEqual(reused.status_code, 200, reused.text)
        self.assertNotEqual(reused.json()["batch_id"], batch["batch_id"])
        self.assertEqual(reused.json()["clips"], batch["clips"])
        # S07 integration: actual batch pins must remain usable by sheet calculation.
        assignment = self.client.post(base + "/sheets-s1", json={"expected_revision": value["expected_revision"],
            "assigned_username": "operator", "rater_id": "operator", "rater_name": "합성 평가자",
            "preprocess": {**state["result_pointer"], "batch_id": batch["batch_id"]}})
        self.assertEqual(assignment.status_code, 201, assignment.text)
        sheet_id = assignment.json()["sheet_id"]
        sheet_url = f"/api/score-sheets-s1/{sheet_id}"
        observations = [{"code": item.code, "value": None, "status": "unobserved", "reason": "합성 미관찰"}
                        for item in load_catalog_v4().rated_items() if item.code not in OPTIONAL_CODES]
        self.assertEqual(self.client.put(sheet_url, json={"expected_revision": 1, "observations": observations}).status_code, 200)
        submitted = self.client.post(sheet_url + "/submit", json={"expected_revision": 2, "reason": "합성 제출"}).json()
        calculated = self.client.post(sheet_url + "/basic-results-s1", json={"input": {"sheet_id": sheet_id,
            "revision": 3, "ref": submitted["manifest_ref"], "hash": submitted["manifest_hash"]}})
        self.assertEqual(calculated.status_code, 201, calculated.text)
        self.assertIsNone(calculated.json()["document"]["calculations"]["owner"]["ratios"])
        result_id = calculated.json()["summary"]["result_id"]
        self.assertEqual(self.client.get(f"/api/basic-results-s1/{result_id}").status_code, 200)
        self.assertEqual(self.client_for("reviewer").get(f"/api/basic-results-s1/{result_id}").status_code, 403)
        held = self.client.put(f"/api/basic-results-s1/{result_id}/judgements", json={"expected_revision": 1, "reason": "합성 판정 보류",
            "decisions": [{"key": "attachment_type", "label": None, "status": "held", "evidence_codes": [], "reason": "관찰 부족"}]})
        self.assertEqual(held.status_code, 200, held.text)
        self.assertEqual(self.client.get(f"/api/basic-results-s1/{result_id}/revisions/1").json()["document"]["revision"], 1)
        # End S07 integration.
        clip = batch["clips"][0]
        url = endpoint + f"/{batch['batch_id']}/clips/{clip['clip_id']}/original"
        downloaded = self.client_for("reviewer").get(url)
        self.assertEqual(downloaded.status_code, 200, downloaded.text if downloaded.status_code != 200 else "")
        self.assertEqual(downloaded.content, self.store.path(clip["original"]["ref"]).read_bytes())
        self.assertEqual(self.client_for("developer").get(url).status_code, 403)
        self.assertEqual(self.client.get(url.replace(clip["clip_id"], "other-clip")).status_code, 404)
        selected = self.client.post(f"/api/cases/{item['case_id']}/sessions",
            json={"expected_revision": value["expected_revision"], "note": "synthetic next session"})
        self.assertEqual(selected.status_code, 200, selected.text)
        historical = self.client_for("reviewer").get(endpoint)
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertFalse(historical.json()["ready"])
        self.assertEqual(self.client_for("reviewer").get(url).status_code, 200)
        self.assertEqual(self.client.post(endpoint, json={**value, "request_id": "old-session",
            "expected_revision": selected.json()["input_revision"]}).status_code, 409)
        self.store.path(clip["ai"]["ref"]).write_bytes(b"tampered derived artifact")
        self.assertEqual(self.client.get(url).status_code, 409)
        self.delete_case(self.get_case(item))
        self.assertEqual(self.client.get(url).status_code, 403)

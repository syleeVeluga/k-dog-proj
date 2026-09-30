"""28 source questions, exact scales, complete means and explicit source editions."""

import csv
from io import BytesIO, StringIO
import json

from openpyxl import Workbook

from app.api import create_app
from app.domain.catalog import SURVEY_IDS
from app.domain.catalog_v3 import SURVEY_VERSION
from tests.support import AppCase


class SurveyV3Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.client = self.client_for("operator")
        self.version = SURVEY_VERSION
        self.item = self.make_case()
        self.path = f"/api/cases/{self.item['case_id']}/survey"

    def save(self, payload):
        result = self.client.put(self.path, json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.item = result.json()
        return self.client.get(self.path + "/result").json()

    def test_exact_scales_zero_and_forbidden_values(self):
        payload = self.answers(self.item)
        for question, value in (("s10", 5), ("s14", 5), ("s01", 0), ("s09", 0), ("s25", 0), ("s10", True), ("s10", 0.5)):
            with self.subTest(question=question, value=value):
                candidate = {**payload, "answers": {**payload["answers"], question: value}}
                self.assertEqual(self.client.put(self.path, json=candidate).status_code, 422)
        for number in range(10, 15):
            payload["answers"][f"s{number:02}"] = 0 if number % 2 == 0 else 4
        result = self.save(payload)
        self.assertEqual(next(value for value in result["items"] if value["item_id"] == "s10")["raw"], 0)
        rejected = self.answers(self.item, not_applicable=("s07",))
        self.assertEqual(self.client.put(self.path, json=rejected).status_code, 422)
        old = {**self.answers(self.item), "survey_version": "catalog-20260913-v2"}
        self.assertEqual(self.client.put(self.path, json=old).status_code, 422)

    def test_eight_source_means_reverse_and_standalone_without_attachment_label(self):
        payload = self.answers(self.item, 5)
        payload["answers"].update(s10=0, s11=4, s12=0, s13=2, s14=4, s22=1, s23=5, s24=2,
                                  s25=4, s26=1, s27=3, s28=5)
        result = self.save(payload)
        self.assertEqual([domain["mean"] for domain in result["domains"]], [5.0, 5.0, 2.0, 2.0, 5.0, 3.0, 2.0, 3.0])
        self.assertEqual([domain["denominator"] for domain in result["domains"]], [6, 3, 2, 3, 7, 2, 1, 3])
        self.assertEqual(result["standalone"]["raw"], 4)
        self.assertEqual([value["converted"] for value in result["items"][-3:]], [5, 3, 1])
        self.assertEqual(result["registration_status"], "all_answered")
        self.assertIsNone(result["registration_complete"])
        self.assertEqual(result["comparison_status"], "pending_policy")
        self.assertFalse({"total", "separation", "attachment_type"} & result.keys())

    def test_partial_policy_reasons_only_edits_and_idempotency(self):
        payload = self.answers(self.item, 3)
        payload["answers"].update(s01=None, s07=None, s10=None)
        payload["blank_reasons"] = {"s07": "본 적 없음"}
        result = self.save(payload)
        self.assertEqual(result["domains"][1]["status"], "insufficient_responses")
        self.assertEqual(result["domains"][0]["status"], "pending_partial")
        self.assertIn("원본 완전응답", result["domains"][1]["reason"])
        self.assertIsNone(result["domains"][1]["mean"])
        self.assertIsNone(result["domains"][1]["denominator"])
        self.assertEqual(result["domains"][2]["answered_count"], 1)
        self.assertEqual(result["comparison_status"], "insufficient_responses")
        self.assertIsNone(next(value for value in result["items"] if value["item_id"] == "s10")["blank_reason"])
        payload["expected_revision"] = self.item["input_revision"]
        unchanged = self.client.put(self.path, json=payload).json()
        self.assertEqual(unchanged["input_revision"], self.item["input_revision"])
        payload["blank_reasons"]["s07"] = "관찰하지 못함"
        self.save(payload)
        self.assertEqual(self.item["input_revision"], unchanged["input_revision"] + 1)
        for reasons in ({"s02": "응답 있음"}, {"s99": "없음"}, {"s07": "   "}):
            self.assertEqual(self.client.put(self.path, json={**payload, "expected_revision": self.item["input_revision"], "blank_reasons": reasons}).status_code, 422)

    def test_csv_xlsx_reasons_and_reimport_use_same_contract(self):
        columns = ["event_id", "participant_id", "survey_version", *SURVEY_IDS, "s07_reason"]
        values = ["TEST", "0001", SURVEY_VERSION, *[None if question == "s07" else 0 if question == "s10" else 3 for question in SURVEY_IDS], "본 적 없음"]
        output = StringIO()
        writer = csv.writer(output)
        writer.writerows([columns, values])
        workbook = Workbook()
        workbook.active.append(columns)
        workbook.active.append(values)
        xlsx = BytesIO()
        workbook.save(xlsx)
        workbook.close()
        for format, data in (("csv", output.getvalue().encode()), ("xlsx", xlsx.getvalue())):
            preview = self.client.post(f"/api/imports/preview?kind=survey&format={format}", content=data).json()
            self.assertEqual(preview["errors"], [])
            self.assertEqual(preview["rows"][0]["survey"]["blank_reasons"], {"s07": "본 적 없음"})
            self.assertEqual(self.client.post("/api/imports/commit", json={"rows": preview["rows"]}).status_code, 200)
            current = self.get_case(self.item)
            self.assertEqual(current["input_revision"], 2)
        template = self.client.get("/api/templates/survey?format=csv").content.decode("utf-8-sig")
        self.assertIn("s28_reason", template)

    def test_mapping_requires_original_edition_and_commit_rechecks_session(self):
        columns = {"event_id": "행사", "participant_id": "번호", **{question: question for question in SURVEY_IDS}}
        data = ("행사,번호," + ",".join(SURVEY_IDS) + "\nTEST,0001," + ",".join(["3"] * 28)).encode()
        mapping = {"columns": columns}
        self.assertEqual(self.client.post("/api/imports/preview", params={"kind": "survey", "format": "csv", "mapping": json.dumps(mapping)}, content=data).status_code, 422)
        mapping["survey_version"] = SURVEY_VERSION
        preview = self.client.post("/api/imports/preview", params={"kind": "survey", "format": "csv", "mapping": json.dumps(mapping)}, content=data).json()
        self.assertEqual(preview["errors"], [])
        new = self.client.post(f"/api/cases/{self.item['case_id']}/sessions", json={"expected_revision": self.item["input_revision"]})
        self.assertEqual(new.status_code, 200)
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": preview["rows"]}).status_code, 409)

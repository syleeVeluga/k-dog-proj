"""U03 saved column mappings: validation, roles, author/admin deletion and survival through backup/restore."""

import shutil

from app import maintenance
from app.auth import create_user
from app.input_models import UserCreate
from app.storage import Store
from tests.support import PASSWORD, AppCase


class FormsPresetsV4Tests(AppCase):
    def preset(self, name="2026 가을 신청폼", **mapping):
        body = {"columns": {"participant_id": "접수번호", "dog_name": "강아지 이름", "s01": "Q1"},
                "answer_labels": {"s01": {"매우 그렇다": 5}}, "layout": "rows", "source_profile": "google-forms", "version": "forms-map-1"}
        body.update(mapping)
        return {"name": name, "mapping": body}

    def test_save_list_and_roles(self):
        saved = self.client.post("/api/forms/presets", json=self.preset())
        self.assertEqual(saved.status_code, 201, saved.text)
        view = saved.json()
        self.assertEqual((view["name"], view["created_by"], view["can_delete"]), ("2026 가을 신청폼", "operator", True))
        self.assertEqual(view["mapping"]["columns"]["dog_name"], "강아지 이름")
        listed = self.client.get("/api/forms/presets").json()
        self.assertEqual([item["preset_id"] for item in listed], [view["preset_id"]])
        for role, status in ((None, 401), ("reviewer", 200), ("developer", 200)):
            other = self.client_for(role)
            self.assertEqual(other.get("/api/forms/presets").status_code, status)
            self.assertEqual(other.post("/api/forms/presets", json=self.preset(f"다른 이름 {role}")).status_code, 401 if role is None else 201)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='forms.preset.save'").fetchone()[0], 3)

    def test_invalid_mappings_and_duplicate_names_are_rejected(self):
        self.assertEqual(self.client.post("/api/forms/presets", json=self.preset()).status_code, 201)
        self.assertEqual(self.client.post("/api/forms/presets", json=self.preset("2026 가을 신청폼")).status_code, 409)
        self.assertEqual(self.client.post("/api/forms/presets", json=self.preset("2026 가을 신청폼".upper())).status_code, 409)
        for bad in (self.preset("x", columns={"unknown": "열"}), self.preset("x", columns={}),
                    self.preset("x", columns={"dog_name": "열", "guardian_name": "열"}),
                    self.preset("x", answer_labels={"s99": {"가": 1}}), self.preset("x", layout="diagonal"),
                    self.preset("x", answer_labels={"s01": {"가": 9}}), self.preset("   ")):
            self.assertEqual(self.client.post("/api/forms/presets", json=bad).status_code, 422, bad)

    def test_only_the_author_or_an_admin_can_delete(self):
        saved = self.client.post("/api/forms/presets", json=self.preset()).json()
        with self.store.connect(write=True) as db:
            create_user(db, UserCreate(username="operator2", password=PASSWORD, role="operator"))
        second = self.client_for()
        self.assertEqual(second.post("/api/auth/login", json={"username": "operator2", "password": PASSWORD}).status_code, 200)
        self.assertFalse(second.get("/api/forms/presets").json()[0]["can_delete"])
        self.assertEqual(second.delete(f"/api/forms/presets/{saved['preset_id']}").status_code, 403)
        self.assertEqual(self.client_for("reviewer").delete(f"/api/forms/presets/{saved['preset_id']}").status_code, 403)
        admin = self.client_for("admin")
        self.assertTrue(admin.get("/api/forms/presets").json()[0]["can_delete"])
        self.assertEqual(admin.delete(f"/api/forms/presets/{saved['preset_id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/forms/presets/{saved['preset_id']}").status_code, 404)
        own = self.client.post("/api/forms/presets", json=self.preset("내 설정")).json()
        self.assertEqual(self.client.delete(f"/api/forms/presets/{own['preset_id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/forms/presets").json(), [])

    def test_presets_survive_backup_and_restore(self):
        saved = self.client.post("/api/forms/presets", json=self.preset()).json()
        backup = self.store.root.parent / (self.store.root.name + "-preset-backup")
        restored = self.store.root.parent / (self.store.root.name + "-preset-restored")
        self.addCleanup(shutil.rmtree, backup, True)
        self.addCleanup(shutil.rmtree, restored, True)
        maintenance.backup(self.store, backup, "admin")
        maintenance.restore(self.store, backup, restored)
        target = Store(restored)
        with target.connect() as db:
            row = db.execute("SELECT name,created_by FROM forms_mapping_presets WHERE preset_id=?", (saved["preset_id"],)).fetchone()
        self.assertEqual((row["name"], row["created_by"]), ("2026 가을 신청폼", "operator"))

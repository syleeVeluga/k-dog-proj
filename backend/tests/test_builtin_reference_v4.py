"""Built-in delivered SF/NF reference definitions (2026-10-21 user decision); data here is synthetic."""
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import comparison_mapping_v4 as mapping, comparisons_v4 as comparisons
from app.api import create_app
from tests import test_comparisons_v4 as fixture
from tests import test_external_comparisons_v4 as external_fixture

SOURCES = ("us2026-stranger-fear", "us2026-nonsocial-fear")


class BuiltinReferenceTests(fixture.ComparisonFixture):
    def start(self):
        with TestClient(create_app(self.store.root), base_url="http://127.0.0.1:8000"):
            pass

    def records(self, source):
        with self.store.connect() as db:
            return db.execute("SELECT actor,detail_json FROM changes WHERE action=? AND target=?", (comparisons.DEFINITION_ACTION, source)).fetchall()

    def test_startup_installs_delivered_values_once_with_builtin_provenance(self):
        self.start()
        loaded = mapping.load()
        for source in SOURCES:
            doc, pointer, _ = self.current(source)
            expected = next(item for item in loaded.external_sources if item.source_id == source)
            self.assertEqual((doc.values.mean, doc.values.standard_deviation, doc.values.valid_n, doc.values.total_n),
                             (expected.mean, expected.standard_deviation, expected.valid_n, expected.total_n))
            self.assertEqual((doc.actor, doc.revision, doc.enabled), (comparisons.BUILTIN_ACTOR, 1, True))
            self.assertIn(loaded.delivery.sha256, doc.number_provenance)
            self.assertIsNone(mapping.definition_mismatch(doc))
            self.assertEqual(doc.evidence[0].hash, hashlib.sha256(mapping.raw()).hexdigest())
            self.assertEqual(self.store.path(doc.evidence[0].ref).read_bytes(), mapping.raw())
        self.start()
        self.assertEqual([len(self.records(source)) for source in SOURCES], [1, 1], "restart never reseeds")
        with self.store.connect() as db:
            self.assertEqual(tuple(db.execute("SELECT role,active FROM users WHERE username=?", (comparisons.BUILTIN_ACTOR,)).fetchone()), ("operator", 0))
        self.assertEqual({item["status"] for item in comparisons.public_sources(self.store, self.user)["sources"]}, {"conditionally_available"})

    def current(self, source):
        with self.store.connect() as db:
            return comparisons.current_definition(self.store, db, source)

    def test_operator_edit_or_retirement_is_never_overwritten(self):
        self.start()
        _, pointer, _ = self.current(SOURCES[0])
        retired = external_fixture.retire(self.store, pointer, SimpleNamespace(username="reviewer"))
        self.start()
        doc, latest, _ = self.current(SOURCES[0])
        self.assertEqual((latest, doc.enabled, doc.actor), (retired, False, "reviewer"))

    def test_existing_operator_definition_prevents_seeding_and_damaged_mapping_skips(self):
        pointer, _ = external_fixture.define(self.store)
        with patch.object(mapping, "raw", return_value=b"{}"):
            self.start()
        self.assertEqual(self.current(SOURCES[0])[1], pointer)
        self.assertIsNone(self.current(SOURCES[1])[0], "a damaged mapping asset seeds nothing")
        self.start()
        self.assertEqual(self.current(SOURCES[0])[1], pointer, "an operator definition is kept")
        self.assertEqual(self.current(SOURCES[1])[0].actor, comparisons.BUILTIN_ACTOR)

    def test_reserved_account_is_hidden_and_cannot_be_managed(self):
        from app.auth import password_hash
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET password_hash=? WHERE username='admin'", (password_hash("Synthetic-Builtin-2026!"),))
        with TestClient(create_app(self.store.root), base_url="http://127.0.0.1:8000", headers={"X-KDOG-Request": "1"}) as client:
            self.assertEqual(client.post("/api/auth/login", json={"username": "admin", "password": "Synthetic-Builtin-2026!"}).status_code, 200)
            self.assertNotIn(comparisons.BUILTIN_ACTOR, [row["username"] for row in client.get("/api/admin/users").json()])
            self.assertEqual(client.patch(f"/api/admin/users/{comparisons.BUILTIN_ACTOR}", json={"role": "operator", "active": True}).status_code, 404)
            self.assertEqual(client.post("/api/admin/users", json={"username": comparisons.BUILTIN_ACTOR, "password": "Synthetic-Builtin-2026!", "role": "operator"}).status_code, 409)
            self.assertEqual(client.post("/api/auth/login", json={"username": comparisons.BUILTIN_ACTOR, "password": "x"}).status_code, 401)

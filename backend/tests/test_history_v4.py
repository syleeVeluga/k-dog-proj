"""Unavailable artifacts must not hide unrelated, accessible S1 history."""
import hashlib
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.api import create_app
from app.auth import password_hash
from app import exports_v4 as exports, validation_data_v4 as validation
from tests import test_external_exports_v4 as export_fixture
from tests import test_validation_data_v4 as validation_fixture


def client_for(test):
    password="Synthetic-History-Only-2026!"
    with test.store.connect(write=True) as db:
        db.execute("UPDATE users SET password_hash=? WHERE username=?",(password_hash(password),test.user.username))
    client=TestClient(create_app(test.store.root),base_url="http://127.0.0.1:8000",headers={"X-KDOG-Request":"1"})
    test.addCleanup(client.close)
    test.assertEqual(client.post("/api/auth/login",json={"username":test.user.username,"password":password}).status_code,200)
    return client


class ExportHistoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=export_fixture.ExternalExportTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store,self.user=self.fixture.store,self.fixture.user
        self.unavailable=exports.create(self.store,self.fixture.request,self.user)
        request=self.fixture.request.model_copy(update={"request_id":"without-external","external_comparisons":[]})
        self.ready=exports.create(self.store,request,self.user)

    def assert_history(self,rows):
        by_id={row["export_id"]:row for row in rows}
        self.assertEqual(by_id[self.ready["export_id"]],self.ready)
        blocked=by_id[self.unavailable["export_id"]]
        self.assertEqual(set(blocked),{"export_id","status","reason"})
        self.assertEqual(blocked["status"],"blocked")

    def test_withdrawn_export_and_ready_export_share_successful_http_history(self):
        self.fixture.withdraw()
        client=client_for(self)
        response=client.get("/api/exports-s1")
        self.assertEqual(response.status_code,200,response.text)
        self.assert_history(response.json())
        self.assertEqual(client.get("/api/exports-s1/"+self.unavailable["export_id"]).status_code,409)
        self.assertEqual(client.get("/api/exports-s1/"+self.unavailable["export_id"]+"/download").status_code,409)
        self.assertEqual(client.get("/api/exports-s1/"+self.ready["export_id"]+"/download").status_code,200)

    def test_damaged_or_missing_snapshot_is_isolated_without_hash_or_counts(self):
        with self.store.connect() as db:record=exports._record(db,self.unavailable["export_id"])
        path=self.store.path(record["ref"])
        original=path.read_bytes()
        for kind in ("damaged","missing"):
            with self.subTest(kind=kind):
                if kind=="damaged":path.write_bytes(b"invalid snapshot")
                else:path.unlink()
                self.assert_history(exports.list_exports(self.store,self.user))
                with self.assertRaises(HTTPException):exports.download(self.store,self.unavailable["export_id"],self.user)
                path.write_bytes(original)

    def test_other_actor_and_account_revocation_are_not_artifact_placeholders(self):
        self.assertEqual(exports.list_exports(self.store,SimpleNamespace(username="admin",role="admin")),[])
        with self.store.connect(write=True) as db:db.execute("UPDATE users SET active=0 WHERE username=?",(self.user.username,))
        with self.assertRaises(HTTPException) as caught:exports.list_exports(self.store,self.user)
        self.assertEqual(caught.exception.status_code,403)
        with self.store.connect(write=True) as db:db.execute("UPDATE users SET active=1 WHERE username=?",(self.user.username,))
        original=exports.view
        def revoke_after_read(*args):
            result=original(*args)
            with self.store.connect(write=True) as db:db.execute("UPDATE users SET active=0 WHERE username=?",(self.user.username,))
            return result
        with patch.object(exports,"view",side_effect=revoke_after_read),self.assertRaises(HTTPException) as caught:
            exports.list_exports(self.store,self.user)
        self.assertEqual(caught.exception.status_code,403)


class ValidationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=validation_fixture.ValidationDataV4Tests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store,self.user=self.fixture.store,self.fixture.user
        self.unavailable=validation.register(self.store,self.fixture.data,self.fixture.request,self.user)
        book=Workbook();book.active.title="Synthetic";book.active["A1"]=2
        output=BytesIO();book.save(output);book.close();data=output.getvalue()
        request=self.fixture.request.model_copy(update={"request_id":"unbound-other-source","expected_sha256":hashlib.sha256(data).hexdigest(),
            "bindings":[],"selections":self.fixture.request.selections[:1]})
        self.ready=validation.register(self.store,data,request,self.user)

    def assert_history(self,rows):
        ready=[row for row in rows if "reference" in row]
        self.assertEqual(ready,[{key:value for key,value in self.ready.items() if key!="document"}])
        blocked=next(row for row in rows if "status" in row)
        self.assertEqual(set(blocked),{"validation_id","status","reason"})
        self.assertEqual(blocked["validation_id"],self.unavailable["reference"]["validation_id"])
        self.assertEqual(blocked["status"],"blocked")

    def test_damaged_reference_and_ready_reference_share_successful_http_history(self):
        self.store.path(self.unavailable["reference"]["ref"]).write_bytes(b"invalid")
        client=client_for(self)
        response=client.get("/api/validation-data-s1")
        self.assertEqual(response.status_code,200,response.text)
        self.assert_history(response.json())
        self.assertEqual(client.get("/api/validation-data-s1/"+self.unavailable["reference"]["validation_id"]).status_code,409)
        self.assertEqual(client.get("/api/validation-data-s1/"+self.ready["reference"]["validation_id"]).status_code,200)

    def test_deleted_binding_does_not_hide_unrelated_source_and_discloses_no_metadata(self):
        with self.store.connect(write=True) as db:db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?",(self.fixture.case_id,))
        self.assert_history(validation.list_records(self.store,self.user))
        with self.assertRaises(HTTPException):validation.view(self.store,self.unavailable["reference"]["validation_id"],self.user)

    def test_other_actor_and_mid_read_account_revocation_fail_at_account_boundary(self):
        self.assertEqual(validation.list_records(self.store,SimpleNamespace(username="admin",role="admin")),[])
        original=validation.view
        def revoke_after_read(*args):
            result=original(*args)
            with self.store.connect(write=True) as db:db.execute("UPDATE users SET active=0 WHERE username=?",(self.user.username,))
            return result
        with patch.object(validation,"view",side_effect=revoke_after_read),self.assertRaises(HTTPException) as caught:
            validation.list_records(self.store,self.user)
        self.assertEqual(caught.exception.status_code,403)
        with self.assertRaises(HTTPException) as caught:validation.list_records(self.store,self.user)
        self.assertEqual(caught.exception.status_code,403)

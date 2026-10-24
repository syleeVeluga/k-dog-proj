from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from app.gemini import ProviderError
from app.gemini_v4 import GeminiScorerV4
from app.gemini_keys import fallback_reason
from app.reset_s1 import pending_remote_cleanup
from app.storage import Store
from app.worker import Worker
from tests import test_run_v4 as run_fixture


class SharedVideoUploadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="kdog-shared-video-")
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name)/"data")
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO users(username,password_hash,role) VALUES ('synthetic','fixture','operator')")
        self.path = Path(temp.name)/"video.mp4"
        self.path.write_bytes(b"synthetic")
        self.clip = SimpleNamespace(clip_id="clip-1", size_bytes=9, sha256=hashlib.sha256(b"synthetic").hexdigest())
        self.lock = threading.Lock()
        self.calls, self.remotes = [], {}
        self.sequence = 0
        self.upload_gate = self.inference_gate = None
        self.inferences_started = threading.Event()
        self.inference_count = 0
        self.fail_delete = False
        self.adapter = GeminiScorerV4(self.store, self.transport)
        self.row = {"run_id":"synthetic-run", "claim_token":"claim-1", "worker_actor":"synthetic"}
        self.context = {"run_id":"synthetic-run", "audit_actor":"synthetic"}
        self.config = {"model":"gemini-3.8-flash", "prompt":"synthetic", "fps":1.0, "processing_mode":"static",
                       "media_resolution":"medium", "max_output_tokens":4096, "thinking_level":"medium"}

    def transport(self, method, url, key, **kwargs):
        with self.lock:
            self.calls.append((method, url, key))
        if url.endswith('/upload/v1beta/files'):
            with self.lock:
                self.sequence += 1
                number = self.sequence
            return {}, {"X-Goog-Upload-URL":f"https://generativelanguage.googleapis.com/synthetic/{number}"}
        if method == "POST" and "/synthetic/" in url:
            if self.upload_gate:
                self.assertTrue(self.upload_gate.wait(5))
            self.assertEqual(kwargs['data'].read(), b'synthetic')
            name = 'files/'+url.rsplit('/',1)[-1]
            remote = {"name":name,"uri":"https://generativelanguage.googleapis.com/v1beta/"+name,"state":"ACTIVE"}
            self.remotes[name] = remote
            return {"file":remote}, {}
        if method == "GET":
            name = 'files/'+url.rsplit('/',1)[-1]
            if name not in self.remotes:
                raise ProviderError('missing',http_status=404)
            return self.remotes[name], {}
        if method == "DELETE":
            if self.fail_delete:
                raise ProviderError('transport',uncertain=True)
            self.remotes.pop('files/'+url.rsplit('/',1)[-1],None)
            return {}, {}
        with self.lock:
            self.inference_count += 1
            if self.inference_count == 4:
                self.inferences_started.set()
        if self.inference_gate:
            self.assertTrue(self.inference_gate.wait(5))
        return {"status":"completed","model":"gemini-3.8-flash","id":"synthetic-response","usage":{"total_tokens":9},
                "steps":[{"type":"model_output","content":[{"type":"text","text":'{"observations":[]}'}]}]}, {}

    def request(self, reference='ref-1', guard=lambda:None, *, adapter=None, attempt=1):
        return (adapter or self.adapter).request_v4([(self.path,self.clip)],self.config,self.context,
            {"type":"object"},guard,selected=('synthetic-key-'+reference,
                {"credential_reference":reference,"credential_slot":"primary","attempt":attempt}))

    def uploads(self):
        return sum(url.endswith('/upload/v1beta/files') for _,url,_ in self.calls)

    def persisted_run(self):
        fixture = run_fixture.RunV4Tests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.store = fixture.store
        run_id = fixture.enqueue()['run_id']
        self.adapter = GeminiScorerV4(self.store,self.transport)
        self.row = {'run_id':run_id,'claim_token':'claim-1','worker_actor':'operator'}
        self.context = {'run_id':run_id,'audit_actor':'operator'}
        return fixture

    def test_retry_wait_retains_upload_but_stop_while_idle_drains_it(self):
        fixture = self.persisted_run()
        self.adapter.begin_run(self.row)
        self.request()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET status='retry_wait' WHERE run_id=?",(self.row['run_id'],))
        self.adapter.finish_run(self.row)
        self.assertEqual(len(pending_remote_cleanup(self.store)),1)
        self.assertFalse(any(method=='DELETE' for method,_,_ in self.calls))
        fixture.action(self.row['run_id'])
        worker = Worker(self.store,observer=self.adapter)
        self.assertFalse(worker.once())
        self.assertEqual(self.inference_count,1)
        self.assertEqual(pending_remote_cleanup(self.store),[])

    def test_restart_after_terminal_publication_cleans_up_without_inference(self):
        self.persisted_run()
        self.adapter.begin_run(self.row)
        self.request()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET status='succeeded' WHERE run_id=?",(self.row['run_id'],))
        recovered = GeminiScorerV4(self.store,self.transport)
        with patch('app.secrets.credential_for_reference',return_value=('synthetic-key-ref-1',{})) as credentials:
            self.assertFalse(Worker(self.store,observer=recovered).once())
        credentials.assert_called_once_with(self.store,'ref-1')
        self.assertEqual(self.inference_count,1)
        self.assertEqual(pending_remote_cleanup(self.store),[])

    def test_retired_credential_remains_pending_without_cross_key_cleanup(self):
        self.persisted_run()
        self.adapter.begin_run(self.row)
        self.request()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET status='stopped' WHERE run_id=?",(self.row['run_id'],))
        recovered = GeminiScorerV4(self.store,self.transport)
        with patch('app.secrets.credential_for_reference',side_effect=ProviderError('developer_settings_required')):
            self.assertFalse(Worker(self.store,observer=recovered).once())
        self.assertEqual(len(pending_remote_cleanup(self.store)),1)
        self.assertFalse(any(method=='DELETE' for method,_,_ in self.calls))

    def test_parallel_requests_share_one_upload_and_deletion_waits_for_all_consumers(self):
        self.adapter.begin_run(self.row)
        self.upload_gate, self.inference_gate = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(self.request) for _ in range(4)]
            self.upload_gate.set()
            self.assertTrue(self.inferences_started.wait(5))
            self.assertEqual(self.uploads(),1)
            closing = pool.submit(self.adapter.finish_run,self.row)
            self.assertFalse(any(m=='DELETE' for m,_,_ in self.calls))
            self.assertFalse(closing.done())
            self.inference_gate.set()
            results = [future.result(timeout=5) for future in futures]
            closing.result(timeout=5)
        self.assertEqual(sum(m=='DELETE' for m,_,_ in self.calls),1)
        self.assertEqual(sum(value[1]['upload_cache']['files'][0]['reused'] for value in results),3)
        self.assertEqual(pending_remote_cleanup(self.store),[])

    def test_keys_and_file_hashes_are_never_cross_reused(self):
        self.adapter.begin_run(self.row)
        self.request('ref-primary')
        self.request('ref-backup')
        self.request('ref-primary')
        self.assertEqual(self.uploads(),2)
        self.path.write_bytes(b'altered!!')
        with self.assertRaises(ProviderError) as error:
            self.request('ref-primary')
        self.assertEqual(error.exception.code,'video_file_changed')
        self.assertEqual(self.uploads(),2)
        self.adapter.finish_run(self.row)
        self.assertEqual({key for method,_,key in self.calls if method=='DELETE'},
                         {'synthetic-key-ref-primary','synthetic-key-ref-backup'})

    def test_new_claim_retries_failed_upload_even_for_a_lower_branch_attempt(self):
        self.adapter.begin_run(self.row)
        original = self.adapter.uploads.transport
        def unavailable(method,url,key,**kwargs):
            raise ProviderError('provider_http_503',retryable=True,http_status=503)
        self.adapter.uploads.transport = unavailable
        with self.assertRaises(ProviderError):
            self.request(attempt=2)
        self.adapter.uploads.transport = original
        self.adapter.begin_run({**self.row,'claim_token':'claim-2'})
        self.request(attempt=1)
        self.assertEqual(self.uploads(),1)
        self.assertEqual(self.inference_count,1)
        self.adapter.finish_run(self.row)

    def test_cache_hit_rechecks_stop_and_does_not_send_inference(self):
        self.adapter.begin_run(self.row)
        self.request()
        def stopped():
            raise HTTPException(409,'stopped')
        with self.assertRaises(HTTPException):
            self.request(guard=stopped)
        self.assertEqual(self.inference_count,1)
        self.adapter.finish_run(self.row)
        self.assertEqual(pending_remote_cleanup(self.store),[])

    def test_restart_revalidates_remote_and_reuses_the_durable_upload(self):
        self.adapter.begin_run(self.row)
        self.request()
        recovered = GeminiScorerV4(self.store,self.transport)
        recovered.begin_run({**self.row,'claim_token':'claim-2'})
        _,usage = self.request(adapter=recovered,attempt=2)
        self.assertTrue(usage['upload_cache']['files'][0]['reused'])
        self.assertEqual(self.uploads(),1)
        self.assertTrue(any(method=='GET' for method,_,_ in self.calls))
        recovered.finish_run(self.row)
        self.assertEqual(pending_remote_cleanup(self.store),[])

    def test_revalidation_and_shared_errors_preserve_fallback_phase_without_foreign_usage(self):
        self.adapter.begin_run(self.row)
        self.request()
        recovered = GeminiScorerV4(self.store,self.transport)
        recovered.begin_run({**self.row,'claim_token':'claim-2'})
        original = recovered.uploads.transport
        def forbidden(method,url,key,**kwargs):
            if method=='GET':
                raise ProviderError('provider_http_403',http_status=403,credential_reason='permission_denied')
            return original(method,url,key,**kwargs)
        recovered.uploads.transport = forbidden
        for _ in range(2):
            with self.assertRaises(ProviderError) as error:
                self.request(adapter=recovered,attempt=2)
            self.assertEqual(error.exception.usage['operation_phase'],'processing')
            self.assertIsNotNone(fallback_reason(error.exception))
            self.assertEqual(error.exception.usage['credential_reference'],'ref-1')
            self.assertEqual(error.exception.usage['provider_intervals'],[])
        recovered.finish_run(self.row)

    def test_missing_remote_is_reuploaded_and_failed_cleanup_remains_durable(self):
        self.adapter.begin_run(self.row)
        self.request()
        self.remotes.clear()
        recovered = GeminiScorerV4(self.store,self.transport)
        recovered.begin_run({**self.row,'claim_token':'claim-2'})
        _,usage = self.request(adapter=recovered,attempt=2)
        self.assertFalse(usage['upload_cache']['files'][0]['reused'])
        self.assertEqual(self.uploads(),2)
        self.fail_delete = True
        recovered.finish_run(self.row)
        pending = pending_remote_cleanup(self.store)
        self.assertEqual(len(pending),1)
        self.assertEqual(pending[0]['credential_reference'],'ref-1')

    def test_lost_replacement_response_never_marks_unknown_upload_deleted(self):
        self.adapter.begin_run(self.row)
        self.request()
        self.remotes.clear()
        recovered = GeminiScorerV4(self.store,self.transport)
        recovered.begin_run({**self.row,'claim_token':'claim-2'})
        original = recovered.uploads.transport
        def lost_response(method,url,key,**kwargs):
            result = original(method,url,key,**kwargs)
            if method=='POST' and '/synthetic/' in url:
                raise ProviderError('provider_connection_lost',uncertain=True)
            return result
        recovered.uploads.transport = lost_response
        with self.assertRaises(ProviderError):
            self.request(adapter=recovered,attempt=2)
        recovered.finish_run(self.row)
        self.assertEqual(len(self.remotes),1)
        pending = pending_remote_cleanup(self.store)
        self.assertEqual(len(pending),1)
        self.assertFalse(pending[0].get('remote_file_name'))

    def test_new_run_never_uses_another_runs_remote(self):
        self.adapter.begin_run(self.row)
        self.request()
        self.context = {**self.context,'run_id':'another-run'}
        other = {**self.row,'run_id':'another-run'}
        self.adapter.begin_run(other)
        self.request()
        self.assertEqual(self.uploads(),2)
        self.adapter.finish_run(other)
        self.assertEqual(len(pending_remote_cleanup(self.store)),1)
        self.adapter.finish_run(self.row)
        self.assertEqual(pending_remote_cleanup(self.store),[])


if __name__ == '__main__':
    unittest.main()

"""Bounded coordinator, settlement barriers and stop/drain tests."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

from fastapi import HTTPException

from app import analysis, scoring_ai_v4, settings_v4
from app.gemini import ProviderError
from app.storage import uid
from app.worker import Worker
from tests import test_run_v4 as fixtures


class ParallelExecutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RunV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store

    def config(self, n, count=8, follow=True):
        groups = scoring_ai_v4.configuration(None, settings_v4.defaults()).stages[:count]
        downstream = groups[0].model_copy(update={"stage": "calculate_v4", "key": "calculation", "provider_call": False, "provider": "program", "model": "program"})
        return self.fixture.config.model_copy(update={"version": "ai-scoring-20261024-pa01",
            "max_parallel_score_groups": n, "max_ai_calls": 100,
            "stages": (*groups, downstream) if follow else groups})

    def enqueue(self, config):
        return self.fixture.enqueue(config=config, value=self.fixture.request.model_copy(update={"request_id": uid()}))["run_id"]

    def test_each_bound_overlaps_and_downstream_waits_for_every_group(self):
        expected = None
        for n in (1, 2, 3, 4):
            with self.subTest(n=n):
                config, lock, ready = self.config(n), threading.Lock(), threading.Barrier(n)
                run_id, active, maximum, ended = self.enqueue(config), 0, 0, []
                order = {stage.key: index for index, stage in enumerate(config.stages)}
                worker = Worker(self.store)
                def handler(snapshot, group, row):
                    def work(step):
                        nonlocal active, maximum
                        if group.stage != "score_v4":
                            self.assertEqual(active, 0)
                            self.assertEqual(len(ended), 8)
                            return {"values": [stage.key for stage in config.stages if stage.stage == "score_v4"], "usage": {}}
                        worker.reserve_call(row, step)
                        with lock:
                            active += 1
                            maximum = max(maximum, active)
                        try:
                            if order[group.key] < n:
                                ready.wait(timeout=10)
                            return {"value": group.key, "usage": {}}
                        finally:
                            with lock:
                                active -= 1
                                ended.append(group.key)
                    return lambda value: value, work
                worker.v4_work = handler
                worker.once()
                self.assertEqual(maximum, n)
                self.assertEqual(self.fixture.row(run_id)["status"], "succeeded")
                with self.store.connect() as db:
                    step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage='calculate_v4'", (run_id,)).fetchone()
                values = analysis.step_payload(self.store, self.fixture.row(run_id), step)["values"]
                if expected is None:
                    expected = values
                self.assertEqual(values, expected)

    def test_retry_wait_blocks_downstream_and_successes_are_not_called_again(self):
        config, calls, downstream = self.config(3, count=4), {}, []
        run_id, worker = self.enqueue(config), Worker(self.store)
        first = config.stages[0].key
        def handler(snapshot, group, row):
            def work(step):
                if group.stage != "score_v4":
                    downstream.append(True)
                    return {"usage": {}}
                worker.reserve_call(row, step)
                calls[group.key] = calls.get(group.key, 0) + 1
                if group.key == first and step["attempt"] == 1:
                    raise ProviderError("synthetic_retry", retryable=True)
                return {"usage": {}}
            return lambda value: value, work
        worker.v4_work = handler
        worker.once()
        self.assertEqual(downstream, [])
        self.assertEqual(self.fixture.row(run_id)["status"], "retry_wait")
        self.fixture.due(run_id)
        worker.once()
        self.assertEqual(self.fixture.row(run_id)["status"], "succeeded")
        self.assertEqual(calls, {group.key: 2 if group.key == first else 1 for group in config.stages if group.stage == "score_v4"})
        self.assertEqual(downstream, [True])

    def test_real_s1_handler_keeps_observation_and_calculation_meaning(self):
        expected = None
        class Provider:
            def request_v4(self, files, config, context, schema, guard):
                guard()
                return {**context["identity"], "observations": [{"code": item["code"], "value": None,
                    "status": "unobserved", "reason": "synthetic fixture: no actual observation"} for item in context["items"]]}, {"cost_usd": None}
        for n in (1, 4):
            pipeline = settings_v4.defaults()
            pipeline.raw_observation_scope_confirmed = True
            pipeline.max_parallel_score_groups = n
            config = scoring_ai_v4.configuration(None, pipeline)
            run_id = self.enqueue(config)
            Worker(self.store, observer=Provider()).once()
            row = self.fixture.row(run_id)
            self.assertEqual(row["status"], "succeeded")
            with self.store.connect() as db:
                steps = db.execute("SELECT * FROM steps WHERE run_id=? AND stage IN ('score_v4','calculate_v4')", (run_id,)).fetchall()
            meaning = {}
            for step in steps:
                payload = analysis.step_payload(self.store, row, step)
                meaning[(step["stage"], step["branch_key"])] = {key: payload[key] for key in ("observations", "linked_memos", "calculations") if key in payload}
            if expected is None:
                expected = meaning
            self.assertEqual(meaning, expected)

    def test_stop_retry_waits_for_old_children_and_rejects_late_outputs(self):
        config, entered, release = self.config(2, count=4, follow=False), threading.Barrier(3), threading.Event()
        run_id, worker, sent = self.enqueue(config), Worker(self.store), []
        def handler(snapshot, group, row):
            def work(step):
                worker.reserve_call(row, step)
                sent.append(group.key)
                entered.wait(timeout=10)
                self.assertTrue(release.wait(timeout=10))
                return {"usage": {"input_tokens": 7}}
            return lambda value: value, work
        worker.v4_work = handler
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(worker.once)
            entered.wait(timeout=10)
            try:
                self.fixture.action(run_id)
                self.assertEqual(self.fixture.row(run_id)["status"], "stopped")
                self.fixture.action(run_id, retry=True)
                with self.assertRaises(HTTPException):
                    Worker(self.store).once()
                self.assertFalse(running.done())
            finally:
                release.set()
            running.result(timeout=10)
        self.assertEqual(len(sent), 2)
        self.assertEqual(self.fixture.row(run_id)["status"], "queued")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps WHERE run_id=? AND status='succeeded'", (run_id,)).fetchone()[0], 0)

    def test_unexpected_exception_drains_other_child_before_failing(self):
        config, started, release = self.config(2, count=2, follow=False), threading.Barrier(2), threading.Event()
        run_id, worker, drained, failed = self.enqueue(config), Worker(self.store), threading.Event(), threading.Event()
        def handler(snapshot, group, row):
            def work(step):
                started.wait(timeout=10)
                if group.key == config.stages[0].key:
                    failed.set()
                    raise RuntimeError("synthetic unexpected task error")
                self.assertTrue(release.wait(timeout=10))
                drained.set()
                return {"usage": {}}
            return lambda value: value, work
        worker.v4_work = handler
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(worker.once)
            try:
                self.assertTrue(failed.wait(timeout=10))
                self.assertFalse(running.done())
                self.assertFalse(drained.is_set())
            finally:
                release.set()
            with self.assertRaises(RuntimeError):
                running.result(timeout=10)
        self.assertTrue(drained.is_set())
        self.assertEqual(self.fixture.row(run_id)["status"], "running")

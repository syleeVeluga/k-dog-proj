"""Comparison pairs and representative survey submissions; every identity and answer is synthetic."""
import shutil
from unittest.mock import patch
from types import SimpleNamespace

from fastapi import HTTPException

from app import cumulative_comparisons_v4 as pairs, maintenance
from app.domain.sheets_v4 import InputPointerV4
from app.storage import Store
from tests import test_comparisons_v4 as fixture


class ParticipationFixture(fixture.ComparisonFixture):
    def pointer(self, index):
        with self.store.connect() as db:
            row = self.store.case(db, self.ids[index])
            return InputPointerV4(manifest_ref=row["manifest_ref"], manifest_hash=row["manifest_hash"]), row["selected_session_id"]

    def link(self, index, request_id, *, pair=None, user=None, source=None):
        return pairs.link(self.store, pairs.PairLinkV4(request_id=request_id, case_id=self.ids[index],
            pair_id=pair.pair_id if pair else None, expected_revision=pair.revision if pair else 0,
            expected_case_pair_id=source.pair_id if source else None, expected_case_pair_revision=source.revision if source else None,
            reason="SYNTHETIC explicit pair link"), user or self.user)

    def submit(self, pair, index, kind, request_id, *, user=None, pointer=None):
        current, session = self.pointer(index)
        return pairs.submit(self.store, pair.pair_id, pairs.SubmissionCreateV4(request_id=request_id, expected_revision=pair.revision,
            kind=kind, case_id=self.ids[index], session_id=session, input=pointer or current,
            evidence=f"SYNTHETIC {kind} evidence"), user or self.user)

    def representative(self, pair):
        with self.store.connect() as db:
            return pairs.representative_input(self.store, db, pairs.read_state(self.store, pairs.pair_head(db, pair.pair_id)))


class PairRegistryTests(ParticipationFixture):
    def test_t07_t08_first_revisit_correction_and_exclusion_rules(self):
        pair = self.link(0, "link-a")
        self.assertEqual((pair.revision, pair.representative_status), (1, "unconfirmed"))
        with self.assertRaises(HTTPException) as caught:
            self.submit(pair, 0, "revisit", "too-early")
        self.assertEqual(caught.exception.status_code, 409)
        first = self.submit(pair, 0, "first", "first-a")
        self.assertEqual((first.revision, first.representative_status), (2, "confirmed"))
        representative = next(item for item in first.submissions if item.representative)
        self.assertEqual(representative.kind, "first")
        self.edit(0, lambda manifest: manifest.sessions[0].survey.update(s10=4))
        revisit = self.submit(first, 0, "revisit", "revisit-a")
        self.assertEqual(revisit.revision, 2, "a revisit never replaces the representative")
        self.assertEqual(next(item for item in revisit.submissions if item.representative).reference, representative.reference)
        self.assertEqual(len(revisit.submissions), 2)
        with self.assertRaises(HTTPException) as caught:
            pairs.submit(self.store, pair.pair_id, pairs.SubmissionCreateV4(request_id="stale-input", expected_revision=2, kind="revisit",
                case_id=self.ids[0], session_id=self.pointer(0)[1], expected_input_revision=1, evidence="SYNTHETIC"), self.user)
        self.assertEqual(caught.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            self.submit(first, 0, "first", "second-first")
        corrected = self.submit(revisit, 0, "correction", "correct-a")
        current = next(item for item in corrected.submissions if item.representative)
        self.assertEqual((corrected.revision, current.kind), (3, "correction"))
        submission, session = self.representative(corrected)
        self.assertEqual(submission.replaces, representative.reference)
        self.assertEqual(session.survey["s10"], 4)
        excluded = pairs.set_status(self.store, pair.pair_id, pairs.PairStatusV4(request_id="exclude", expected_revision=3,
            status="excluded", reason="SYNTHETIC exclusion"), self.user)
        self.assertEqual((excluded.status, excluded.representative_status), ("excluded", "confirmed"))
        self.assertEqual(next(item for item in excluded.submissions if item.representative).reference, current.reference,
                         "exclusion keeps the representative and never promotes a revisit")
        included = pairs.set_status(self.store, pair.pair_id, pairs.PairStatusV4(request_id="include", expected_revision=4,
            status="included", reason="SYNTHETIC re-include"), self.reviewer)
        self.assertEqual((included.status, included.actor), ("included", "reviewer"))

    def test_t03_partial_answers_are_submittable_and_raw_inputs_are_unchanged(self):
        before = self.pointer(1)
        raw = self.store.path(before[0].manifest_ref).read_bytes()
        pair = self.submit(self.link(1, "link-b"), 1, "first", "first-b")
        self.assertEqual(pair.representative_status, "confirmed")
        self.assertEqual(self.pointer(1), before)
        self.assertEqual(self.store.path(before[0].manifest_ref).read_bytes(), raw)
        submission, session = self.representative(pair)
        self.assertIsNone(session.survey["s13"])
        self.assertEqual(submission.input, before[0])

    def test_survey_save_or_new_input_after_submission_keeps_the_pinned_representative(self):
        pair = self.submit(self.link(0, "link"), 0, "first", "first")
        pinned, _ = self.pointer(0)
        self.edit(0, lambda manifest: manifest.sessions[0].survey.update(s11=4))
        self.assertNotEqual(self.pointer(0)[0], pinned)
        submission, session = self.representative(pair)
        self.assertEqual((submission.input, session.survey["s11"]), (pinned, 0))
        view = pairs.pair_view(self.store, self.user, pair.pair_id)
        self.assertEqual(view.revision, pair.revision, "ordinary survey saves create no submission event")

    def test_t16_idempotent_replay_conflicting_payload_and_concurrent_links(self):
        pair = self.link(0, "same")
        self.assertEqual(self.link(0, "same"), pair)
        with self.assertRaises(HTTPException) as caught:
            pairs.link(self.store, pairs.PairLinkV4(request_id="same", case_id=self.ids[1], expected_revision=0, reason="other"), self.user)
        self.assertEqual(caught.exception.status_code, 409)
        with self.assertRaises(HTTPException) as caught:
            self.link(0, "duplicate-case")
        self.assertEqual(caught.exception.status_code, 409, "a case belongs to one active pair")
        joined = self.link(2, "join", pair=pair)
        with self.assertRaises(HTTPException) as caught:
            self.link(1, "stale", pair=pair)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(len(joined.cases), 2)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action=?", (pairs.STATE_ACTION,)).fetchone()[0], 2)

    def test_moving_the_representative_case_clears_the_old_pair_and_blocks_plain_reinclusion(self):
        old = self.submit(self.link(0, "old"), 0, "first", "first")
        old = pairs.set_status(self.store, old.pair_id, pairs.PairStatusV4(request_id="exclude", expected_revision=old.revision,
            status="excluded", reason="SYNTHETIC wrong identity"), self.user)
        new = self.link(1, "new")
        with self.assertRaises(HTTPException):
            self.link(0, "move-without-source", pair=new)
        moved = self.link(0, "move", pair=new, source=old)
        self.assertEqual({case.case_id for case in moved.cases}, {self.ids[0], self.ids[1]})
        self.assertEqual(moved.representative_status, "unconfirmed", "the destination representative is never replaced implicitly")
        previous = pairs.pair_view(self.store, self.user, old.pair_id)
        self.assertEqual((previous.cases, previous.representative_status), ((), "unconfirmed"))
        self.assertEqual(len(previous.submissions), 1, "the moved representative stays as history")
        reincluded = pairs.set_status(self.store, old.pair_id, pairs.PairStatusV4(request_id="include", expected_revision=previous.revision,
            status="included", reason="SYNTHETIC"), self.user)
        self.assertEqual((reincluded.status, reincluded.representative_status), ("included", "unconfirmed"),
                         "re-inclusion never resurrects the moved representative")
        with self.assertRaises(HTTPException) as caught:
            self.submit(reincluded, 0, "first", "foreign-case")
        self.assertEqual(caught.exception.status_code, 409, "the moved case now belongs to another pair")

    def test_t18_t20_wrong_inputs_inactive_accounts_and_shared_business_access(self):
        pair = self.link(0, "link", user=SimpleNamespace(username="admin"))
        self.assertEqual(pair.actor, "admin")
        other, session = self.pointer(1)
        with self.assertRaises(HTTPException) as caught:
            pairs.submit(self.store, pair.pair_id, pairs.SubmissionCreateV4(request_id="foreign", expected_revision=1, kind="first",
                case_id=self.ids[0], session_id=session, input=other, evidence="SYNTHETIC"), self.user)
        self.assertEqual(caught.exception.status_code, 409)
        current, _ = self.pointer(0)
        with self.assertRaises(HTTPException) as caught:
            pairs.submit(self.store, pair.pair_id, pairs.SubmissionCreateV4(request_id="session", expected_revision=1, kind="first",
                case_id=self.ids[0], session_id="missing-session", input=current, evidence="SYNTHETIC"), self.user)
        self.assertEqual(caught.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            self.submit(pair, 1, "first", "unlinked-case")
        reviewer = self.submit(pair, 0, "first", "reviewer-first", user=self.reviewer)
        self.assertEqual(next(item for item in reviewer.submissions if item.representative).actor, "reviewer")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='reviewer'")
        for action in (lambda: pairs.inventory(self.store, self.reviewer), lambda: self.link(1, "inactive", user=self.reviewer)):
            with self.assertRaises(HTTPException) as caught:
                action()
            self.assertEqual(caught.exception.status_code, 403)

    def test_t11_inventory_counts_unconfirmed_and_never_auto_registers(self):
        empty = pairs.inventory(self.store, self.user)
        self.assertEqual((empty.pairs, empty.counts["unlinked_s1_cases"]), ((), 3))
        self.link(0, "a")
        self.submit(self.link(1, "b"), 1, "first", "first-b")
        shown = pairs.inventory(self.store, self.user, self.ids[0])
        self.assertEqual(shown.counts, {"pairs": 2, "included_confirmed": 1, "representative_unconfirmed": 1, "excluded": 0, "unlinked_s1_cases": 1})
        self.assertIsNotNone(shown.case_pair_id)
        with self.store.connect() as db:
            self.assertFalse(db.execute("SELECT 1 FROM changes WHERE action=? AND actor NOT IN ('operator')", (pairs.SUBMISSION_ACTION,)).fetchone())


class PairMaintenanceTests(ParticipationFixture):
    def test_t21_backup_clean_restore_keep_states_revisits_and_inputs(self):
        pair = self.submit(self.link(0, "link"), 0, "first", "first")
        first_input, _ = self.pointer(0)
        self.edit(0, lambda manifest: manifest.sessions[0].survey.update(s12=4))
        pair = self.submit(pair, 0, "revisit", "revisit")
        with self.store.connect() as db:
            refs = maintenance.references(self.store, db)
            states = [pairs.read_state(self.store, pairs.pair_head(db, pair.pair_id))]
        for item in pair.submissions:
            self.assertIn(item.reference.ref, refs)
        self.assertIn(pair.reference.ref, refs)
        self.assertIn(states[0].previous.ref, refs)
        self.assertIn(first_input.manifest_ref, refs)
        orphan = self.store.path("comparisons/pairs/orphan.json")
        orphan.write_text("{}", encoding="utf-8")
        backup = self.store.root.parent / (self.store.root.name + "-backup")
        restored = self.store.root.parent / (self.store.root.name + "-restored")
        self.addCleanup(shutil.rmtree, backup, True)
        self.addCleanup(shutil.rmtree, restored, True)
        maintenance.backup(self.store, backup, "admin")
        maintenance.clean(self.store)
        self.assertFalse(orphan.exists())
        for item in pair.submissions:
            self.assertTrue(self.store.path(item.reference.ref).exists())
        maintenance.restore(self.store, backup, restored)
        target = Store(restored)
        self.assertEqual(pairs.pair_view(target, self.user, pair.pair_id), pairs.pair_view(self.store, self.user, pair.pair_id))
        damaged = self.store.path(pair.submissions[-1].reference.ref)
        damaged.write_bytes(damaged.read_bytes() + b" ")
        with self.assertRaises(HTTPException):
            maintenance.clean(self.store)


class PairReviewFixTests(ParticipationFixture):
    def test_correction_stays_on_the_representative_case(self):
        pair = self.link(0, "a")
        pair = self.link(1, "b", pair=pair)
        pair = self.submit(pair, 0, "first", "first")
        with self.assertRaises(HTTPException) as caught:
            self.submit(pair, 1, "correction", "other-case")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.submit(pair, 1, "revisit", "revisit-b").revision, pair.revision)

    def test_unconfirmed_pair_can_be_excluded_and_reincluded(self):
        pair = self.link(0, "a")
        excluded = pairs.set_status(self.store, pair.pair_id, pairs.PairStatusV4(request_id="x", expected_revision=1, status="excluded", reason="SYNTHETIC"), self.user)
        included = pairs.set_status(self.store, pair.pair_id, pairs.PairStatusV4(request_id="i", expected_revision=excluded.revision, status="included", reason="SYNTHETIC"), self.user)
        self.assertEqual((included.status, included.representative_status), ("included", "unconfirmed"))

    def test_reinclusion_rechecks_question_identity(self):
        pair = self.submit(self.link(0, "a"), 0, "first", "first")
        excluded = pairs.set_status(self.store, pair.pair_id, pairs.PairStatusV4(request_id="x", expected_revision=pair.revision, status="excluded", reason="SYNTHETIC"), self.user)
        with patch.object(pairs.mapping, "question_signature", return_value="0" * 64):
            with self.assertRaises(HTTPException) as caught:
                pairs.set_status(self.store, pair.pair_id, pairs.PairStatusV4(request_id="i", expected_revision=excluded.revision, status="included", reason="SYNTHETIC"), self.user)
        self.assertEqual(caught.exception.status_code, 409)

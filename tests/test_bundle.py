import csv
import os
import tempfile
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings

from tier_plugin import dummy, features, model_adapter, pages, progress
from tier_plugin.exams import DEFAULT_EXAM_PROFILES
from tier_plugin.models import StudentTier

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def tier_of(exam, persona, seed):
    sim = dummy.simulate(exam, persona, seed, NOW)
    f, _ = features.compute_features(now=NOW, **sim)
    return model_adapter.CompositeBackend().predict(f).tier


class PersonaTierTest(TestCase):
    """Sanity table: a made-up study pattern should land in a believable tier, for both exams."""
    EXPECT = {
        "steady_topper": {"Tier 1"},
        "consistent_average": {"Tier 1"},
        "fast_improver": {"Tier 1"},
        "struggling": {"Tier 3"},
        "narrow_specialist": {"Tier 2", "Tier 3"},   # 3 subjects only: never Tier 1
        "early_dropout": {"Tier 2", "Tier 3"},
        "new_joiner": {"Not enough data"},
    }

    def test_personas_land_in_expected_tiers(self):
        for exam in DEFAULT_EXAM_PROFILES:
            for persona, allowed in self.EXPECT.items():
                for seed in range(8):
                    self.assertIn(tier_of(exam, persona, seed), allowed, "%s %s seed %s" % (exam, persona, seed))

    def test_slipping_and_crammer_are_not_the_bottom(self):
        for exam in DEFAULT_EXAM_PROFILES:
            for seed in range(8):
                self.assertNotEqual(tier_of(exam, "slipping", seed), "Tier 3")
                self.assertNotEqual(tier_of(exam, "crammer", seed), "Tier 3")

    def test_same_seed_same_learner(self):
        a = dummy.simulate("gate_cse", "slipping", 3, NOW)
        b = dummy.simulate("gate_cse", "slipping", 3, NOW)
        self.assertEqual(a["subsection_rows"], b["subsection_rows"])
        self.assertEqual(a["activity_days"], b["activity_days"])


class ProgressTest(TestCase):
    def prog(self, persona, **kw):
        sim = dummy.simulate("gate_cse", persona, 1, NOW)
        f, ss = features.compute_features(now=NOW, **sim)
        return progress.build_progress(exam="gate_cse", features=f, subject_scores=ss, tier="Tier 1", **kw)

    def test_all_subjects_listed_and_statuses(self):
        d = self.prog("narrow_specialist")
        self.assertEqual(len(d["subjects"]), 14)
        self.assertEqual(d["overall"]["subjects_attempted"], 3)
        self.assertEqual(sum(1 for s in d["subjects"] if s["status"] == "not_started"), 11)
        self.assertTrue(d["next_step"].startswith("Start the"))
        self.assertIn("Not started yet", [n["title"] for n in d["notifications"]])

    def test_struggling_gets_warning_first(self):
        d = self.prog("struggling")
        self.assertEqual(d["notifications"][0]["level"], "warn")
        self.assertIn("Needs more practice", [n["title"] for n in d["notifications"]])

    def test_new_joiner_gets_start_message(self):
        d = self.prog("new_joiner")
        self.assertEqual(d["notifications"][0]["title"], "Start your first practice quiz")
        self.assertIsNone(d["overall"]["average_score"])

    def test_inactive_learner_is_told(self):
        f = {k: 0.0 for k in features.FEATURE_ORDER}
        f.update(S_weighted=60.0, recency_score=0.2, regularity_index=0.5)  # ~23 days idle
        d = progress.build_progress(exam="ugc_net_cs", features=f, subject_scores={"Software Engineering": 60.0})
        self.assertEqual(d["overall"]["days_since_active"], 23)
        self.assertEqual(d["notifications"][0]["title"], "Time to get back")

    def test_tier_hidden_unless_allowed(self):
        self.assertIsNone(self.prog("steady_topper")["tier"])
        d = self.prog("steady_topper", show_tier=True)
        self.assertEqual(d["tier"]["name"], "Tier 1")


@override_settings(TIER_COURSE_EXAMS={"course-v1:T+G+1": "gate_cse"})
class SeedCommandTest(TestCase):
    def run_seed(self, **kw):
        out = os.path.join(tempfile.mkdtemp(), "r.csv")
        call_command("seed_dummy_learners", course_id="course-v1:T+G+1", report=out, **kw)
        return out

    def test_creates_learners_rows_and_report(self):
        out = self.run_seed(count=12)
        self.assertEqual(StudentTier.objects.count(), 12)
        rows = list(csv.DictReader(open(out)))
        self.assertEqual(len(rows), 12)
        self.assertIn("new_joiner", {r["persona"] for r in rows})
        self.assertEqual({r["username"] for r in rows}, set(get_user_model().objects.values_list("username", flat=True)))

    def test_rerun_does_not_duplicate_and_clean_removes(self):
        self.run_seed(count=5)
        self.run_seed(count=5)
        self.assertEqual(StudentTier.objects.count(), 5)
        call_command("seed_dummy_learners", course_id="course-v1:T+G+1", clean=True)
        self.assertEqual(get_user_model().objects.filter(username__startswith="dummy_").count(), 0)
        self.assertEqual(StudentTier.objects.count(), 0)

    def test_every_dummy_user_gets_a_profile(self):
        """Without a UserProfile the Open edX login page fails with 'User has no profile'."""
        from unittest import mock
        fake = mock.Mock()
        mods = {"common": mock.Mock(), "common.djangoapps": mock.Mock(), "common.djangoapps.student": mock.Mock(),
                "common.djangoapps.student.models": mock.Mock(UserProfile=fake)}
        with mock.patch.dict("sys.modules", mods):
            self.run_seed(count=4)
        self.assertEqual(fake.objects.get_or_create.call_count, 4)
        self.assertEqual(fake.objects.get_or_create.call_args_list[0].kwargs["defaults"], {"name": "dummy_gate_01"})

    def test_unlisted_course_refused(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("seed_dummy_learners", course_id="course-v1:X+Y+Z")

    @override_settings(TIER_SHOW_TO_LEARNERS=False)
    def test_progress_for_reads_seeded_row(self):
        self.run_seed(count=3)
        user = get_user_model().objects.get(username="dummy_gate_01")
        d = progress.progress_for(user, "course-v1:T+G+1")
        self.assertEqual(d["exam"], "gate_cse")
        self.assertIsNone(d["tier"])
        self.assertIsNone(progress.progress_for(user, ""))  # always per course, never "latest"
        self.assertEqual([c["course_id"] for c in progress.courses_for(user)], ["course-v1:T+G+1"])
        self.assertIsNone(progress.progress_for(user, "course-v1:X+Y+Z"))


class ExplanationTest(TestCase):
    def setUp(self):
        sim = dummy.simulate("gate_cse", "slipping", 1, NOW)
        self.f, self.ss = features.compute_features(now=NOW, **sim)
        self.pred = model_adapter.CompositeBackend().predict(self.f)

    def test_composite_breakdown_is_exact(self):
        ref = sum(model_adapter._terms(dict({k: 0.0 for k in features.FEATURE_ORDER}, **model_adapter.BENCHMARK)).values())
        self.assertAlmostEqual(sum(e["impact"] for e in self.pred.explanation), self.pred.score - ref, places=3)
        impacts = [abs(e["impact"]) for e in self.pred.explanation]
        self.assertEqual(impacts, sorted(impacts, reverse=True))

    def prog(self, show, version="composite-v1", explanation=None, tier=None, score=None):
        return progress.build_progress(exam="gate_cse", features=self.f, subject_scores=self.ss, show_tier=show,
                                       tier=tier or self.pred.tier, score=self.pred.score if score is None else score,
                                       model_version=version, explanation=explanation)

    def test_hidden_unless_allowed(self):
        d = self.prog(False)
        self.assertNotIn("cpf", d)
        self.assertNotIn("drivers", d)

    def test_cpf_and_drivers_shown(self):
        d = self.prog(True)
        self.assertEqual(d["cpf"]["score"], round(100 * self.pred.score, 1))
        self.assertEqual(d["cpf"]["kind"], "readiness")
        self.assertTrue(d["drivers"]["helping"] and d["drivers"]["holding_back"])
        self.assertTrue(all(x["points"] > 0 for x in d["drivers"]["helping"]))
        self.assertTrue(all(x["points"] < 0 and x["text"] for x in d["drivers"]["holding_back"]))
        self.assertEqual(d["cpf"]["next_level"]["name"], "Tier 1")

    def test_trained_model_shap_is_passed_through(self):
        shap = [{"feature": "S_weighted", "impact": -0.12}, {"feature": "recency_score", "impact": 0.05}]
        d = self.prog(True, version="v7", explanation=shap, tier="Tier 2", score=0.55)
        self.assertEqual(d["cpf"]["kind"], "model")
        self.assertEqual(d["drivers"]["holding_back"][0]["points"], -12.0)
        self.assertEqual(d["drivers"]["helping"][0]["label"], "Recent activity")
        self.assertIsNone(d["cpf"]["next_level"])

    def test_cap_note_for_low_scores(self):
        f = {k: 0.0 for k in features.FEATURE_ORDER}
        f.update(S_weighted=30.0, completion_rate=0.2, regularity_index=1.0, recency_score=1.0, longest_gap_days=0.0)
        pred = model_adapter.CompositeBackend().predict(f)
        d = progress.build_progress(exam="gate_cse", features=f, subject_scores={}, show_tier=True, tier=pred.tier,
                                    score=pred.score, model_version=pred.version)
        self.assertEqual(pred.tier, "Tier 3")
        self.assertIn("below 40%", d["drivers"]["cap_note"])

    @override_settings(TIER_MODEL_BACKEND="http", TIER_MODEL_URL="http://m/x")
    def test_http_explanation_is_parsed_and_junk_ignored(self):
        from unittest import mock
        reply = {"tier": "Tier 2", "score": 0.5, "version": "v1",
                 "explanation": [{"feature": "a", "impact": 0.01}, {"feature": "b", "impact": -0.2}, {"bad": 1}, {"feature": "c", "impact": "x"}]}
        with mock.patch("requests.post", return_value=mock.Mock(json=lambda: reply, raise_for_status=lambda: None)):
            pred = model_adapter.get_backend().predict(self.f)
        self.assertEqual([e["feature"] for e in pred.explanation], ["b", "a"])


class EnrollmentGateTest(TestCase):
    def test_not_enrolled_gets_nothing(self):
        from unittest import mock
        enroll = mock.Mock()
        enroll.is_enrolled.return_value = False
        mods = {"common": mock.Mock(), "common.djangoapps": mock.Mock(), "common.djangoapps.student": mock.Mock(),
                "common.djangoapps.student.models": mock.Mock(CourseEnrollment=enroll),
                "opaque_keys": mock.Mock(), "opaque_keys.edx": mock.Mock(), "opaque_keys.edx.keys": mock.Mock()}
        user = get_user_model().objects.create(username="x")
        StudentTier.objects.create(user=user, course_id="course-v1:T+G+1", exam="gate_cse", tier="Tier 1",
                                   features={k: 0.0 for k in features.FEATURE_ORDER}, subject_scores={})
        with mock.patch.dict("sys.modules", mods):
            self.assertIsNone(progress.progress_for(user, "course-v1:T+G+1"))
            self.assertEqual(progress.courses_for(user), [])
            enroll.is_enrolled.return_value = True
            self.assertEqual(progress.progress_for(user, "course-v1:T+G+1")["exam"], "gate_cse")


@override_settings(LOGIN_URL="/login/")
class PageTest(TestCase):
    def test_page_needs_login_and_serves_widget(self):
        rf = RequestFactory()
        req = rf.get("/api/tier/progress/")
        from django.contrib.auth.models import AnonymousUser
        req.user = AnonymousUser()
        self.assertEqual(pages.progress_page(req).status_code, 302)
        req.user = get_user_model().objects.create(username="u")
        resp = pages.progress_page(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/api/tier/v1/me/", resp.content)

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
        self.assertEqual(progress.progress_for(user, "")["course_id"], "course-v1:T+G+1")  # latest course
        self.assertIsNone(progress.progress_for(user, "course-v1:X+Y+Z"))


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
        self.assertIn(b"/api/tier/v1/me/progress/", resp.content)

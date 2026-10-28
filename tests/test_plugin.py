from datetime import datetime, timedelta, timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from tier_plugin import features, model_adapter
from tier_plugin.exams import exam_for_course
from tier_plugin.models import StudentTier
from tier_plugin.service import compute_and_save

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


def day(n):  # n days ago
    return NOW - timedelta(days=n)


def strong():
    f = {k: 0.0 for k in features.FEATURE_ORDER}
    f.update(S_weighted=80.0, balance_index=0.9, subjects_covered_frac=0.8, regularity_index=0.9,
             longest_gap_days=3.0, activity_trend_slope=0.5, completion_rate=0.8, recency_score=0.9,
             error_retry_ratio=0.5)
    return f


class FeatureMathTest(TestCase):
    """Numbers below were worked out by hand."""

    def setUp(self):
        rows = [
            {"when": day(10), "earned": 5, "possible": 10, "name": "Algebra: Quiz"},
            {"when": day(5), "earned": 8, "possible": 10, "name": "Logic: Quiz"},
            {"when": day(1), "earned": 9, "possible": 10, "name": "Algebra: Quiz 2"},
        ]
        self.f, self.subjects = features.compute_features(
            now=NOW, enrolled_at=day(21), subsection_rows=rows,
            activity_days={TODAY - timedelta(days=d) for d in (10, 5, 1)},
            problem_attempts=[1, 3, 2, 0], total_graded=4, subjects=["Algebra", "Logic"],
        )

    def test_academic(self):
        # weights 0.64, 0.8, 1.0 on 50, 80, 90 -> 186 / 2.44
        self.assertAlmostEqual(self.f["S_weighted"], 76.2295, places=3)
        self.assertAlmostEqual(self.f["slope_assessments"], 20.0, places=6)
        self.assertEqual(self.subjects, {"Algebra": 70.0, "Logic": 80.0})
        self.assertAlmostEqual(self.f["subjects_covered_frac"], 1.0)
        self.assertAlmostEqual(self.f["balance_index"], 1 - 5 / 75, places=6)

    def test_consistency(self):
        # 3 weeks since enrolling; active days per week (oldest to newest) = 0, 1, 2
        self.assertAlmostEqual(self.f["regularity_index"], 2 / 3, places=6)
        self.assertAlmostEqual(self.f["active_day_ratio"], 3 / 21, places=6)
        self.assertAlmostEqual(self.f["activity_trend_slope"], 1.0, places=6)
        self.assertEqual(self.f["longest_gap_days"], 5.0)
        self.assertAlmostEqual(self.f["recency_score"], 0.931063, places=5)  # exp(-1/14)

    def test_behaviour(self):
        self.assertAlmostEqual(self.f["completion_rate"], 0.75)
        self.assertAlmostEqual(self.f["error_retry_ratio"], 2 / 3, places=6)
        self.assertAlmostEqual(self.f["avg_attempts_per_problem"], 2.0)
        self.assertAlmostEqual(self.f["progression_speed"], 1.0)
        self.assertEqual(self.f["days_enrolled"], 21.0)

    def test_content_completion(self):
        # 12 of 30 videos+pages done, 5 of 10 videos done
        f, _ = features.compute_features(
            now=NOW, enrolled_at=day(21), subsection_rows=[], activity_days=set(), problem_attempts=[],
            total_graded=4, subjects=["Algebra"], content_blocks=(12, 30, 5, 10))
        self.assertAlmostEqual(f["content_completion"], 0.4)
        self.assertAlmostEqual(f["video_completion"], 0.5)
        f, _ = features.compute_features(
            now=NOW, enrolled_at=day(21), subsection_rows=[], activity_days=set(), problem_attempts=[],
            total_graded=4, subjects=["Algebra"], content_blocks=None)
        self.assertEqual((f["content_completion"], f["video_completion"]), (0.0, 0.0))

    def test_all_features_present_and_numeric(self):
        self.assertEqual(set(self.f), set(features.FEATURE_ORDER))
        self.assertTrue(all(isinstance(v, float) for v in self.f.values()))

    def test_learner_with_no_activity(self):
        f, subjects = features.compute_features(
            now=NOW, enrolled_at=day(10), subsection_rows=[], activity_days=set(),
            problem_attempts=[], total_graded=5, subjects=["Algebra"])
        self.assertEqual(f["S_weighted"], 0.0)
        self.assertEqual(f["recency_score"], 0.0)
        self.assertEqual(f["longest_gap_days"], 10.0)
        self.assertEqual(subjects, {})

    def test_longest_subject_name_wins(self):
        rows = [{"when": day(1), "earned": 1, "possible": 2, "name": "Data Structures and Algorithms: Quiz"}]
        _, subjects = features.compute_features(
            now=NOW, enrolled_at=day(7), subsection_rows=rows, activity_days=set(),
            problem_attempts=[], total_graded=1, subjects=["Algorithms", "Data Structures and Algorithms"])
        self.assertEqual(list(subjects), ["Data Structures and Algorithms"])


class CompositeTest(TestCase):
    def test_no_evidence_is_not_tiered(self):
        pred = model_adapter.CompositeBackend().predict({k: 0.0 for k in features.FEATURE_ORDER})
        self.assertEqual((pred.tier, pred.score), ("Not enough data", None))

    def test_strong_learner(self):
        self.assertEqual(model_adapter.CompositeBackend().predict(strong()).tier, "Tier 1")

    def test_weak_learner(self):
        f = {k: 0.0 for k in features.FEATURE_ORDER}
        f.update(S_weighted=20.0, completion_rate=0.1, longest_gap_days=30.0)
        self.assertEqual(model_adapter.CompositeBackend().predict(f).tier, "Tier 3")

    def test_worked_example(self):
        f, _ = TestFeature.f_and_s()
        pred = model_adapter.CompositeBackend().predict(f)
        self.assertEqual(pred.tier, "Tier 1")
        # v0.5: quiz completion weighs 0.25 (was 0.4) and content completion (0 here) takes 0.15:
        # 0.7994 + (1/0.85)*0.20*(0.25-0.40)*0.75 = 0.7994 - 0.0265 = 0.7729
        self.assertAlmostEqual(pred.score, 0.7729, places=3)


class TestFeature:
    @staticmethod
    def f_and_s():
        rows = [
            {"when": day(10), "earned": 5, "possible": 10, "name": "Algebra: Quiz"},
            {"when": day(5), "earned": 8, "possible": 10, "name": "Logic: Quiz"},
            {"when": day(1), "earned": 9, "possible": 10, "name": "Algebra: Quiz 2"},
        ]
        return features.compute_features(
            now=NOW, enrolled_at=day(21), subsection_rows=rows,
            activity_days={TODAY - timedelta(days=d) for d in (10, 5, 1)},
            problem_attempts=[1, 3, 2, 0], total_graded=4, subjects=["Algebra", "Logic"])


class MigrationTest(TestCase):
    def test_migrations_match_models(self):
        call_command("makemigrations", "tier_plugin", "--check", "--dry-run")


@override_settings(TIER_COURSE_EXAMS={"course-v1:A+B+C": "gate_cse"})
class ServiceTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="s1")

    def test_exam_mapping(self):
        self.assertEqual(exam_for_course("course-v1:A+B+C"), "gate_cse")
        self.assertIsNone(exam_for_course("course-v1:X+Y+Z"))

    @mock.patch("tier_plugin.features.collect_features")
    def test_saves_and_updates_one_row(self, collect):
        collect.return_value = (strong(), {"Algorithms": 80.0})
        compute_and_save(self.user, "course-v1:A+B+C")
        row = StudentTier.objects.get()
        self.assertEqual((row.tier, row.exam, row.model_version), ("Tier 1", "gate_cse", "composite-v1"))
        self.assertEqual(row.subject_scores, {"Algorithms": 80.0})
        weak = {k: 0.0 for k in features.FEATURE_ORDER}
        weak.update(S_weighted=20.0, completion_rate=0.1, longest_gap_days=30.0)
        collect.return_value = (weak, {})
        compute_and_save(self.user, "course-v1:A+B+C")
        self.assertEqual(StudentTier.objects.count(), 1)
        self.assertEqual(StudentTier.objects.get().tier, "Tier 3")

    @mock.patch("tier_plugin.features.collect_features")
    def test_unlisted_course_is_skipped(self, collect):
        self.assertIsNone(compute_and_save(self.user, "course-v1:X+Y+Z"))
        collect.assert_not_called()
        self.assertEqual(StudentTier.objects.count(), 0)


class HttpBackendTest(TestCase):
    @override_settings(TIER_MODEL_BACKEND="http", TIER_MODEL_URL="http://model.local/predict", TIER_MODEL_TOKEN="tok")
    @mock.patch("requests.post")
    def test_http_payload_and_reply(self, post):
        post.return_value = mock.Mock(json=lambda: {"tier": "Gold", "score": 0.93, "version": "v3"},
                                      raise_for_status=lambda: None)
        ctx = {"exam": "ugc_net_cs", "subject_scores": {"Software Engineering": 61.0}}
        pred = model_adapter.get_backend().predict(strong(), ctx)
        self.assertEqual((pred.tier, pred.score, pred.version), ("Gold", 0.93, "v3"))
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://model.local/predict")
        body = kwargs["json"]
        self.assertEqual((body["schema_version"], body["exam"]), (2, "ugc_net_cs"))
        self.assertEqual(body["subject_scores"], {"Software Engineering": 61.0})
        self.assertEqual(body["features"], strong())
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")

    @override_settings(TIER_MODEL_BACKEND="http", TIER_MODEL_URL="")
    def test_http_needs_url(self):
        with self.assertRaises(RuntimeError):
            model_adapter.get_backend().predict(strong())

    @override_settings(TIER_MODEL_BACKEND="nope")
    def test_unknown_backend(self):
        with self.assertRaises(RuntimeError):
            model_adapter.get_backend()


class PickleBackendTest(TestCase):
    @override_settings(TIER_MODEL_BACKEND="pickle", TIER_MODEL_PATH="/x/model.joblib")
    def test_feature_order_is_respected(self):
        fake = mock.Mock()
        fake.predict.return_value = ["B"]
        fake.predict_proba.return_value = [[0.2, 0.8]]
        model_adapter.PickleBackend._model = None
        with mock.patch.dict("sys.modules", {"joblib": mock.Mock(load=lambda p: fake)}):
            pred = model_adapter.get_backend().predict(strong())
        model_adapter.PickleBackend._model = None
        self.assertEqual((pred.tier, pred.score), ("B", 0.8))
        self.assertEqual(fake.predict.call_args[0][0][0], [strong()[k] for k in features.FEATURE_ORDER])

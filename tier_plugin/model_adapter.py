"""Connects your tier model to the plugin. Pick a backend with TIER_MODEL_BACKEND."""
import logging
import math
from collections import namedtuple

from django.conf import settings

from .features import FEATURE_ORDER

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2
Prediction = namedtuple("Prediction", ["tier", "score", "version", "explanation"], defaults=(None,))

# Placeholder weights, taken from the DIKSHA-CALAS label (academic 40, consistency 25,
# behaviour 20). Its 15% equity part is not used here, so the rest is rescaled.
# These are NOT learned from exam results. Replace with your trained model (http backend).
W_ACADEMIC, W_CONSISTENCY, W_BEHAVIOUR = 0.40, 0.25, 0.20
LOW_SCORE = 40.0      # weighted score (%) below this is always Tier 3
MIN_COVERAGE = 0.5    # Tier 1 needs at least this share of the exam's subjects attempted


def _clip(x):
    return max(0.0, min(1.0, x))


# A made-up "benchmark learner" the breakdown is measured against: each factor's impact is how many
# readiness points the learner is above or below this benchmark on that factor.
BENCHMARK = dict(S_weighted=60.0, balance_index=0.7, subjects_covered_frac=0.5, regularity_index=0.5,
                 longest_gap_days=7.0, activity_trend_slope=0.0, completion_rate=0.5, recency_score=0.5,
                 error_retry_ratio=0.3)


def _terms(f):
    """The readiness score is the sum of these nine terms (each 0 to a small maximum)."""
    k = 1.0 / (W_ACADEMIC + W_CONSISTENCY + W_BEHAVIOUR)
    return {
        "S_weighted": k * W_ACADEMIC * 0.6 * f["S_weighted"] / 100,
        "balance_index": k * W_ACADEMIC * 0.2 * _clip(f["balance_index"]),
        "subjects_covered_frac": k * W_ACADEMIC * 0.2 * _clip(f["subjects_covered_frac"]),
        "regularity_index": k * W_CONSISTENCY * 0.5 * f["regularity_index"],
        "longest_gap_days": k * W_CONSISTENCY * 0.25 * (1 - min(f["longest_gap_days"] / 14.0, 1.0)),
        "activity_trend_slope": k * W_CONSISTENCY * 0.25 * _clip(0.5 + f["activity_trend_slope"] / 2.0),
        "completion_rate": k * W_BEHAVIOUR * 0.4 * f["completion_rate"],
        "recency_score": k * W_BEHAVIOUR * 0.3 * f["recency_score"],
        "error_retry_ratio": k * W_BEHAVIOUR * 0.3 * f["error_retry_ratio"],
    }


def explain_composite(f):
    """Factor-by-factor breakdown: [{"feature", "impact"}], impact in readiness units (0-1), biggest first.
    Because the composite score is a plain sum, this is exact (it is what SHAP values would give for it).
    The impacts add up to: readiness(this learner) - readiness(benchmark learner)."""
    ref = _terms(dict({k: 0.0 for k in FEATURE_ORDER}, **BENCHMARK))
    cur = _terms(f)
    rows = [{"feature": n, "impact": round(cur[n] - ref[n], 5)} for n in cur]
    return sorted(rows, key=lambda r: -abs(r["impact"]))


def cap_reason(f, tier):
    """Plain-language reason when a guard rail (below) limited the tier, else None."""
    if f.get("S_weighted", 0) < LOW_SCORE and f.get("completion_rate", 0) > 0:
        return "Your level is held at Tier 3 while your weighted quiz score is below %d%%." % LOW_SCORE
    if f.get("subjects_covered_frac", 0) < MIN_COVERAGE and tier == "Tier 2":
        return "Tier 1 needs at least half the subjects attempted. Attempt more subjects to unlock it."
    return None


class CompositeBackend:
    """Transparent readiness score from the three groups of features. Use until you have
    real outcome data to train on. It is a summary of activity and scores, not a prediction."""

    version = "composite-v1"

    def predict(self, f, context=None):
        if f.get("S_weighted", 0) == 0 and f.get("completion_rate", 0) == 0:
            return Prediction("Not enough data", None, self.version)  # never tier on no evidence
        readiness = sum(_terms(f).values())
        high, mid = getattr(settings, "TIER_THRESHOLDS", (0.65, 0.40))
        tier = "Tier 1" if readiness >= high else "Tier 2" if readiness >= mid else "Tier 3"
        # Guard rails (found with the dummy learners): steady habits must not hide weak scores or
        # a narrow syllabus. Low scores cap at Tier 3; covering under half the subjects caps at Tier 2.
        if f["S_weighted"] < LOW_SCORE:
            tier = "Tier 3"
        elif f["subjects_covered_frac"] < MIN_COVERAGE and tier == "Tier 1":
            tier = "Tier 2"
        return Prediction(tier, round(readiness, 4), self.version, explain_composite(f))


class HttpBackend:
    """Your model runs as its own service (for example on your other site).

    Request : POST TIER_MODEL_URL
      {"schema_version": 2, "exam": "gate_cse", "features": {...14 numbers...},
       "subject_scores": {"Operating Systems": 72.5, ...}, "profile": {...only if enabled...}}
    Response: {"tier": "Tier 1", "score": 0.91, "version": "v3",
               "explanation": [{"feature": "S_weighted", "impact": 0.07}, ...]}   (all but tier optional)
    "score" is the probability (0-1). "explanation" is the SHAP value per feature, in the same units as score
    (positive pushes the score up). Feature names must be the plugin's names (FEATURE_ORDER).
    """

    def predict(self, features, context=None):
        import requests

        url = getattr(settings, "TIER_MODEL_URL", "")
        if not url:
            raise RuntimeError("TIER_MODEL_URL is not set")
        headers = {}
        token = getattr(settings, "TIER_MODEL_TOKEN", "")
        if token:
            headers["Authorization"] = "Bearer " + token
        body = {"schema_version": SCHEMA_VERSION, "features": features}
        body.update(context or {})
        resp = requests.post(url, json=body, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        explanation = data.get("explanation")
        if isinstance(explanation, dict):  # also accept {"feature": impact}
            explanation = [{"feature": k, "impact": v} for k, v in explanation.items()]
        clean = []
        for item in explanation or []:
            try:
                clean.append({"feature": str(item["feature"]), "impact": float(item["impact"])})
            except (KeyError, TypeError, ValueError):
                continue  # ignore malformed entries, keep the tier
        clean.sort(key=lambda r: -abs(r["impact"]))
        return Prediction(str(data["tier"]), data.get("score"), str(data.get("version", "http")), clean)


class PickleBackend:
    """A scikit-learn style model saved with joblib. Only load files you created yourself:
    loading a pickle can run code. The file must exist inside the LMS container, and
    scikit-learn must be installed in the image."""

    version = "pickle"
    _model = None

    def _load(self):
        if PickleBackend._model is None:
            import joblib

            path = getattr(settings, "TIER_MODEL_PATH", "")
            if not path:
                raise RuntimeError("TIER_MODEL_PATH is not set")
            PickleBackend._model = joblib.load(path)
        return PickleBackend._model

    def predict(self, features, context=None):
        model = self._load()
        row = [[features.get(name, 0.0) for name in FEATURE_ORDER]]
        label = model.predict(row)[0]
        score = None
        if hasattr(model, "predict_proba"):
            score = float(max(model.predict_proba(row)[0]))
        return Prediction(str(label), score, self.version)


_BACKENDS = {"composite": CompositeBackend, "rules": CompositeBackend, "http": HttpBackend, "pickle": PickleBackend}


def get_backend():
    name = getattr(settings, "TIER_MODEL_BACKEND", "composite")
    try:
        return _BACKENDS[name]()
    except KeyError:
        raise RuntimeError("Unknown TIER_MODEL_BACKEND %r (use composite, http or pickle)" % name)

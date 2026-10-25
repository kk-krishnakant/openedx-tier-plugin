"""Connects your tier model to the plugin. Pick a backend with TIER_MODEL_BACKEND."""
import logging
import math
from collections import namedtuple

from django.conf import settings

from .features import FEATURE_ORDER

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2
Prediction = namedtuple("Prediction", ["tier", "score", "version"])

# Placeholder weights, taken from the DIKSHA-CALAS label (academic 40, consistency 25,
# behaviour 20). Its 15% equity part is not used here, so the rest is rescaled.
# These are NOT learned from exam results. Replace with your trained model (http backend).
W_ACADEMIC, W_CONSISTENCY, W_BEHAVIOUR = 0.40, 0.25, 0.20
LOW_SCORE = 40.0      # weighted score (%) below this is always Tier 3
MIN_COVERAGE = 0.5    # Tier 1 needs at least this share of the exam's subjects attempted


def _clip(x):
    return max(0.0, min(1.0, x))


class CompositeBackend:
    """Transparent readiness score from the three groups of features. Use until you have
    real outcome data to train on. It is a summary of activity and scores, not a prediction."""

    version = "composite-v1"

    def predict(self, f, context=None):
        if f.get("S_weighted", 0) == 0 and f.get("completion_rate", 0) == 0:
            return Prediction("Not enough data", None, self.version)  # never tier on no evidence
        academic = 0.6 * f["S_weighted"] / 100 + 0.2 * _clip(f["balance_index"]) + 0.2 * _clip(f["subjects_covered_frac"])
        consistency = (
            0.5 * f["regularity_index"]
            + 0.25 * (1 - min(f["longest_gap_days"] / 14.0, 1.0))
            + 0.25 * _clip(0.5 + f["activity_trend_slope"] / 2.0)
        )
        behaviour = 0.4 * f["completion_rate"] + 0.3 * f["recency_score"] + 0.3 * f["error_retry_ratio"]
        readiness = (W_ACADEMIC * academic + W_CONSISTENCY * consistency + W_BEHAVIOUR * behaviour) / (
            W_ACADEMIC + W_CONSISTENCY + W_BEHAVIOUR
        )
        high, mid = getattr(settings, "TIER_THRESHOLDS", (0.65, 0.40))
        tier = "Tier 1" if readiness >= high else "Tier 2" if readiness >= mid else "Tier 3"
        # Guard rails (found with the dummy learners): steady habits must not hide weak scores or
        # a narrow syllabus. Low scores cap at Tier 3; covering under half the subjects caps at Tier 2.
        if f["S_weighted"] < LOW_SCORE:
            tier = "Tier 3"
        elif f["subjects_covered_frac"] < MIN_COVERAGE and tier == "Tier 1":
            tier = "Tier 2"
        return Prediction(tier, round(readiness, 4), self.version)


class HttpBackend:
    """Your model runs as its own service (for example on your other site).

    Request : POST TIER_MODEL_URL
      {"schema_version": 2, "exam": "gate_cse", "features": {...14 numbers...},
       "subject_scores": {"Operating Systems": 72.5, ...}, "profile": {...only if enabled...}}
    Response: {"tier": "Tier 1", "score": 0.91, "version": "v3"}   (score and version optional)
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
        return Prediction(str(data["tier"]), data.get("score"), str(data.get("version", "http")))


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

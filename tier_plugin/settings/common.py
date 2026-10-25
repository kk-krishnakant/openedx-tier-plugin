def plugin_settings(settings):
    """Defaults. Override any of these from Tutor (see README)."""
    # Which course prepares for which exam. Courses not listed here are never tiered.
    # Example: {"course-v1:TestOrg+GATE101+2026": "gate_cse"}   (exams: gate_cse, ugc_net_cs)
    settings.TIER_COURSE_EXAMS = getattr(settings, "TIER_COURSE_EXAMS", {})
    # "composite" (built-in placeholder) | "http" (your model behind an API) | "pickle" (joblib file)
    settings.TIER_MODEL_BACKEND = getattr(settings, "TIER_MODEL_BACKEND", "composite")
    settings.TIER_MODEL_URL = getattr(settings, "TIER_MODEL_URL", "")
    settings.TIER_MODEL_TOKEN = getattr(settings, "TIER_MODEL_TOKEN", "")
    settings.TIER_MODEL_PATH = getattr(settings, "TIER_MODEL_PATH", "")
    # (Tier 1 starts at, Tier 2 starts at) for the composite backend.
    settings.TIER_THRESHOLDS = getattr(settings, "TIER_THRESHOLDS", (0.65, 0.40))
    # Send level of education and age (if learners gave them) to your model API.
    settings.TIER_USE_CONTEXTUAL = getattr(settings, "TIER_USE_CONTEXTUAL", False)
    # Learners can only read their own tier through the API when this is True.
    settings.TIER_SHOW_TO_LEARNERS = getattr(settings, "TIER_SHOW_TO_LEARNERS", False)
    # Wait this long after a grade change before recomputing (merges bursts of changes).
    settings.TIER_DEBOUNCE_SECONDS = getattr(settings, "TIER_DEBOUNCE_SECONDS", 60)

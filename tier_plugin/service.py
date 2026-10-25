from . import features as features_module
from .exams import exam_for_course
from .model_adapter import get_backend
from .models import StudentTier


def compute_and_save(user, course_key):
    """Collect features, ask the model, store the result.
    Returns the StudentTier row, or None if the course is not listed in TIER_COURSE_EXAMS."""
    exam = exam_for_course(course_key)
    if exam is None:
        return None
    features, subject_scores = features_module.collect_features(user, course_key, exam)
    context = {"exam": exam, "subject_scores": subject_scores}
    profile = features_module.collect_profile(user)
    if profile:
        context["profile"] = profile
    prediction = get_backend().predict(features, context)
    obj, _ = StudentTier.objects.update_or_create(
        user=user,
        course_id=str(course_key),
        defaults={
            "exam": exam,
            "tier": prediction.tier,
            "score": prediction.score,
            "features": features,
            "subject_scores": subject_scores,
            "model_version": prediction.version,
        },
    )
    return obj

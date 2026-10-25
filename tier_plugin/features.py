"""Turns Open edX data into model inputs (academic, consistency, behaviour).

compute_features() is plain Python (easy to test). collect_features() reads the
Open edX database and calls it. Names follow the DIKSHA-CALAS feature dictionary
where an equivalent exists; see the README table.
"""
import json
import math
from datetime import timedelta

from django.conf import settings

from .exams import get_profile

# The model gets features in exactly this order (used by the "pickle" backend).
# Changing this list changes the model's input schema: retrain when you do.
FEATURE_ORDER = [
    # academic
    "S_weighted",              # recency-weighted mean of graded-subsection scores, 0-100
    "balance_index",           # 1 - std/mean across subject averages (0 if fewer than 2 subjects)
    "slope_assessments",       # score change per assessment (positive = improving)
    "subjects_covered_frac",   # share of the exam's subjects attempted at least once
    # consistency
    "active_day_ratio",        # active days / days in the window
    "regularity_index",        # share of recent weeks with at least one active day
    "activity_trend_slope",    # change in active days per week, per week
    "longest_gap_days",        # longest break between active days (including up to today)
    # behaviour
    "completion_rate",         # attempted graded subsections / all graded subsections
    "error_retry_ratio",       # of problems attempted, share tried again (self-correction)
    "avg_attempts_per_problem",
    "progression_speed",       # graded subsections attempted per week
    "recency_score",           # exp(-days since last activity / 14)
    "days_enrolled",
]


def _slope(ys):
    n = len(ys)
    if n < 2:
        return 0.0
    mx, my = (n - 1) / 2.0, sum(ys) / n
    den = sum((i - mx) ** 2 for i in range(n))
    return sum((i - mx) * (y - my) for i, y in enumerate(ys)) / den


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _subject_for(name, subjects):
    lowered = (name or "").lower()
    for subject in sorted(subjects, key=len, reverse=True):  # longest name wins
        if subject.lower() in lowered:
            return subject
    return None


def compute_features(*, now, enrolled_at, subsection_rows, activity_days, problem_attempts,
                     total_graded, subjects, decay=0.8, window_weeks=8):
    """subsection_rows: [{"when": datetime, "earned": float, "possible": float, "name": str}]
    activity_days: set of dates the learner did something. problem_attempts: attempts per problem.
    Returns (features, subject_scores)."""
    f = {name: 0.0 for name in FEATURE_ORDER}
    today = now.date()
    days_enrolled = max(0, (now - enrolled_at).days) if enrolled_at else 0
    f["days_enrolled"] = float(days_enrolled)

    # ---- academic
    rows = sorted((r for r in subsection_rows if r["possible"] > 0), key=lambda r: r["when"])
    pct = [100.0 * r["earned"] / r["possible"] for r in rows]
    n = len(pct)
    if n:
        weights = [decay ** (n - 1 - i) for i in range(n)]  # newest = 1
        f["S_weighted"] = sum(w * p for w, p in zip(weights, pct)) / sum(weights)
        f["slope_assessments"] = _slope(pct)
    by_subject = {}
    for r, p in zip(rows, pct):
        subject = _subject_for(r["name"], subjects)
        if subject:
            by_subject.setdefault(subject, []).append(p)
    subject_scores = {s: sum(v) / len(v) for s, v in by_subject.items()}
    if subjects:
        f["subjects_covered_frac"] = len(subject_scores) / len(subjects)
    vals = list(subject_scores.values())
    if len(vals) >= 2:
        mean = sum(vals) / len(vals)
        if mean > 0:
            std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
            f["balance_index"] = _clip(1 - std / mean)

    # ---- consistency (activity per week, oldest to newest)
    days = sorted(d for d in activity_days if d <= today)
    n_weeks = max(1, min(window_weeks, math.ceil(days_enrolled / 7)))
    weekly = []
    for k in range(n_weeks - 1, -1, -1):
        end = today - timedelta(days=7 * k)
        start = end - timedelta(days=7)
        weekly.append(sum(1 for d in days if start < d <= end))
    f["regularity_index"] = sum(1 for x in weekly if x > 0) / n_weeks
    f["active_day_ratio"] = sum(weekly) / (7.0 * n_weeks)
    f["activity_trend_slope"] = _slope(weekly)
    if days:
        gaps = [(b - a).days for a, b in zip(days, days[1:])] + [(today - days[-1]).days]
        f["longest_gap_days"] = float(max(gaps))
        f["recency_score"] = math.exp(-(today - days[-1]).days / 14.0)
    else:
        f["longest_gap_days"] = float(days_enrolled)
        f["recency_score"] = 0.0

    # ---- behaviour
    if total_graded:
        f["completion_rate"] = _clip(n / total_graded)
    tried = [a for a in problem_attempts if a >= 1]
    if tried:
        f["error_retry_ratio"] = sum(1 for a in tried if a >= 2) / len(tried)
        f["avg_attempts_per_problem"] = sum(tried) / len(tried)
    f["progression_speed"] = n / n_weeks
    return f, subject_scores


def collect_features(user, course_key, exam):
    """Reads Open edX data for one learner and returns (features, subject_scores)."""
    # Imported here so this file can be imported outside the LMS (tests).
    from common.djangoapps.student.models import CourseEnrollment
    from django.utils import timezone
    from lms.djangoapps.courseware.models import StudentModule
    from lms.djangoapps.grades.models import PersistentSubsectionGrade
    from xmodule.modulestore.django import modulestore
    from xmodule.modulestore.exceptions import ItemNotFoundError

    store = modulestore()
    rows = []
    for g in PersistentSubsectionGrade.objects.filter(user_id=user.id, course_id=course_key):
        try:
            name = store.get_item(g.usage_key).display_name
        except ItemNotFoundError:
            name = ""
        rows.append({
            "when": g.first_attempted or g.modified,
            "earned": float(g.earned_graded or 0),
            "possible": float(g.possible_graded or 0),
            "name": name,
        })

    activity_days = {r["when"].date() for r in rows}
    for created, modified in StudentModule.objects.filter(
        student=user, course_id=course_key
    ).values_list("created", "modified"):
        activity_days.add(created.date())
        activity_days.add(modified.date())

    problem_attempts = []
    for state in StudentModule.objects.filter(
        student=user, course_id=course_key, module_type="problem"
    ).values_list("state", flat=True):
        try:
            problem_attempts.append(int((json.loads(state) or {}).get("attempts", 0)))
        except (ValueError, TypeError):
            pass

    course = store.get_course(course_key)
    total_graded = sum(
        1 for chapter in course.get_children() for seq in chapter.get_children() if getattr(seq, "graded", False)
    )
    enrollment = CourseEnrollment.get_enrollment(user, course_key)

    return compute_features(
        now=timezone.now(),
        enrolled_at=enrollment.created if enrollment else None,
        subsection_rows=rows,
        activity_days=activity_days,
        problem_attempts=problem_attempts,
        total_graded=total_graded,
        subjects=get_profile(exam)["subjects"],
    )


def collect_profile(user):
    """Optional background fields. Off unless TIER_USE_CONTEXTUAL = True, and only sent to your own model API.
    Open edX only has these if learners filled them in at signup."""
    if not getattr(settings, "TIER_USE_CONTEXTUAL", False):
        return {}
    from django.utils import timezone

    profile = getattr(user, "profile", None)
    if profile is None:
        return {}
    age = None
    if profile.year_of_birth:
        age = timezone.now().year - profile.year_of_birth
    return {"level_of_education": profile.level_of_education or None, "age": age}

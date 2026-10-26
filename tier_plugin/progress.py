"""What a learner sees: progress summary and notifications, built from the stored StudentTier row.

build_progress() is plain Python (easy to test). progress_for() reads the database.
Notifications are rules over the stored inputs; nothing extra is stored. The tier itself is
included only when TIER_SHOW_TO_LEARNERS is True.
"""
import math

from django.conf import settings

from .exams import exam_for_course, get_profile

WEAK_BELOW = 50.0     # subject average (%) below this is "needs work"
STRONG_FROM = 75.0    # at or above this is "strong"
TIER_TEXT = {
    "Tier 1": "On track",
    "Tier 2": "Making progress",
    "Tier 3": "Needs more practice",
    "Not enough data": "Not enough data yet",
}


# feature -> (label, advice when it holds the score back, praise when it helps)
FEATURE_INFO = {
    "S_weighted": ("Quiz scores", "Retake the quizzes where you scored lowest and revise those notes first.", "Your recent quiz scores are strong."),
    "balance_index": ("Balance across subjects", "Your scores differ a lot between subjects. Give the weakest ones extra time.", "You are doing evenly well across subjects."),
    "subjects_covered_frac": ("Syllabus coverage", "Attempt the practice quiz of every subject, even the ones you find hard.", "You have attempted most subjects."),
    "regularity_index": ("Weekly routine", "Study a little every week. Short regular sessions beat rare long ones.", "You study in most weeks."),
    "longest_gap_days": ("Breaks between study days", "Avoid long gaps. Even 20 minutes on a busy day keeps the momentum.", "You rarely take long breaks."),
    "activity_trend_slope": ("Study frequency trend", "Your activity is falling week by week. Fix a daily time slot.", "Your activity is rising week by week."),
    "completion_rate": ("Quizzes completed", "Complete the remaining graded quizzes and mock tests.", "You have completed most graded quizzes."),
    "recency_score": ("Recent activity", "You have been away for a while. Do one short session today.", "You studied very recently."),
    "error_retry_ratio": ("Retrying mistakes", "When an answer is wrong, read the explanation and retry the problem.", "You retry problems after mistakes."),
    "slope_assessments": ("Score trend", "Your quiz scores are not improving yet. Review your mistakes before the next quiz.", "Your quiz scores are improving."),
    "active_day_ratio": ("Days studied", "Study on more days of the week.", "You study on many days."),
    "avg_attempts_per_problem": ("Attempts per problem", "Understand the solution before retrying again and again.", "Your attempts per problem look healthy."),
    "progression_speed": ("Pace", "You complete fewer quizzes per week than the plan needs.", "You are keeping pace with the plan."),
    "days_enrolled": ("Time since joining", "", ""),
}
MIN_IMPACT_POINTS = 0.5  # ignore factors that move the score by less than this many points (out of 100)


def _drivers(explanation):
    """Split the per-feature impacts into what helps and what holds the score back (points out of 100)."""
    helping, holding = [], []
    for item in explanation or []:
        points = round(100.0 * item["impact"], 1)
        label, advice, praise = FEATURE_INFO.get(item["feature"], (item["feature"].replace("_", " ").capitalize(), "Improve this area.", ""))
        if points >= MIN_IMPACT_POINTS:
            helping.append({"feature": item["feature"], "label": label, "points": points, "text": praise})
        elif points <= -MIN_IMPACT_POINTS:
            holding.append({"feature": item["feature"], "label": label, "points": points, "text": advice})
    helping.sort(key=lambda r: -r["points"])
    holding.sort(key=lambda r: r["points"])
    return helping[:3], holding[:3]


def _days_since_active(recency_score):
    if not recency_score or recency_score <= 0:
        return None
    return int(round(-14.0 * math.log(min(recency_score, 1.0))))


def _note(level, title, text):
    return {"level": level, "title": title, "text": text}


def build_progress(*, exam, features, subject_scores, updated_at=None, course_id="", tier=None, show_tier=False,
                   score=None, model_version="", explanation=None):
    profile = get_profile(exam)
    subjects = profile["subjects"]
    f = features or {}
    scores = subject_scores or {}

    rows = []
    for name in subjects:
        if name in scores:
            s = round(float(scores[name]), 1)
            status = "weak" if s < WEAK_BELOW else "strong" if s >= STRONG_FROM else "ok"
            rows.append({"name": name, "score": s, "status": status})
        else:
            rows.append({"name": name, "score": None, "status": "not_started"})
    attempted = [r for r in rows if r["score"] is not None]
    weak = sorted((r for r in attempted if r["status"] == "weak"), key=lambda r: r["score"])
    untouched = [r for r in rows if r["score"] is None]

    days_idle = _days_since_active(f.get("recency_score"))
    overall = {
        "average_score": round(sum(r["score"] for r in attempted) / len(attempted), 1) if attempted else None,
        "subjects_attempted": len(attempted),
        "subjects_total": len(subjects),
        "quizzes_attempted_pct": round(100 * f.get("completion_rate", 0.0)),
        "active_weeks_pct": round(100 * f.get("regularity_index", 0.0)),
        "days_since_active": days_idle,
    }

    notes = []
    if not attempted:
        notes.append(_note("info", "Start your first practice quiz",
                           "Your progress will appear here a few minutes after you submit a graded quiz."))
    else:
        if days_idle is not None and days_idle >= 5:
            notes.append(_note("warn", "Time to get back",
                               "You have not studied for %d days. A short session today keeps your revision on schedule." % days_idle))
        if weak:
            names = ", ".join("%s (%.0f%%)" % (r["name"], r["score"]) for r in weak[:3])
            notes.append(_note("warn", "Needs more practice", "Scores below %d%% in: %s. Revisit the notes and retry the quiz." % (WEAK_BELOW, names)))
        if f.get("slope_assessments", 0.0) >= 3:
            notes.append(_note("good", "Scores are rising", "Your recent quiz scores are higher than your earlier ones. Keep this pace."))
        elif f.get("slope_assessments", 0.0) <= -3:
            notes.append(_note("warn", "Scores are slipping", "Your recent quiz scores are lower than your earlier ones. Revise the last topics before moving on."))
        if f.get("regularity_index", 0.0) >= 0.75 and (days_idle is None or days_idle < 5):
            notes.append(_note("good", "Steady routine", "You studied in %d%% of recent weeks." % overall["active_weeks_pct"]))
        elif f.get("regularity_index", 0.0) < 0.5:
            notes.append(_note("info", "Study a little every week", "You were active in %d%% of recent weeks. Regular short sessions beat rare long ones." % overall["active_weeks_pct"]))
        strong = [r for r in attempted if r["status"] == "strong"]
        if strong:
            notes.append(_note("good", "Strong subjects", "Well done in: %s." % ", ".join(r["name"] for r in strong[:3])))
        if untouched:
            notes.append(_note("info", "Not started yet", "%d of %d subjects have no quiz attempt yet." % (len(untouched), len(subjects))))
    order = {"warn": 0, "info": 1, "good": 2}
    notes.sort(key=lambda n: order[n["level"]])

    if weak:
        next_step = "Revise %s and retry its practice quiz." % weak[0]["name"]
    elif untouched:
        next_step = "Start the %s practice quiz." % untouched[0]["name"]
    elif attempted:
        lowest = min(attempted, key=lambda r: r["score"])
        next_step = "Improve your lowest subject: %s (%.0f%%)." % (lowest["name"], lowest["score"])
    else:
        next_step = "Open Week 1 and take your first practice quiz."

    out = {
        "course_id": course_id,
        "exam": exam,
        "exam_label": profile["label"],
        "updated_at": updated_at.isoformat() if updated_at else None,
        "overall": overall,
        "subjects": rows,
        "notifications": notes,
        "next_step": next_step,
        "tier": None,
    }
    if show_tier and tier:
        out["tier"] = {"name": tier, "meaning": TIER_TEXT.get(tier, "")}
        if score is not None:
            from .model_adapter import cap_reason, explain_composite

            composite = (model_version or "").startswith("composite")
            if composite and not explanation:  # the composite breakdown is exact, so compute it from the stored inputs
                explanation = explain_composite(f)
            helping, holding = _drivers(explanation)
            next_level = None
            if composite:
                high, mid = getattr(settings, "TIER_THRESHOLDS", (0.65, 0.40))
                target = {"Tier 3": ("Tier 2", mid), "Tier 2": ("Tier 1", high)}.get(tier)
                if target and score < target[1]:
                    next_level = {"name": target[0], "at": round(100 * target[1], 1), "gap": round(100 * (target[1] - score), 1)}
            out["cpf"] = {
                "score": round(100.0 * score, 1),
                "kind": "readiness" if composite else "model",
                "next_level": next_level,
                "note": ("A readiness index (0-100) built from your quiz scores and study habits. It is not a probability of passing the exam."
                         if composite else "Estimated by the trained model from your quiz scores and study habits."),
            }
            out["drivers"] = {"helping": helping, "holding_back": holding,
                              "benchmark_note": "Points compare you with a benchmark learner (average scores, studies in half the weeks)." if composite else "",
                              "cap_note": cap_reason(f, tier) if composite else None}
    return out


def is_enrolled(user, course_id):
    """True if the learner is actively enrolled in the course. Outside Open edX (tests) there is
    no enrollment table, so this returns True there."""
    try:
        from common.djangoapps.student.models import CourseEnrollment
        from opaque_keys.edx.keys import CourseKey
    except ImportError:
        return True
    try:
        return bool(CourseEnrollment.is_enrolled(user, CourseKey.from_string(course_id)))
    except Exception:
        return False


def _title(course_id):
    try:
        from opaque_keys.edx.keys import CourseKey
        from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
        return CourseOverview.objects.get(id=CourseKey.from_string(course_id)).display_name or course_id
    except Exception:
        return course_id


def courses_for(user):
    """The learner's own tiered courses (enrolled only), one entry per course."""
    from .models import StudentTier

    out = []
    for row in StudentTier.objects.filter(user=user).order_by("course_id"):
        if is_enrolled(user, row.course_id):
            out.append({"course_id": row.course_id, "title": _title(row.course_id),
                        "exam_label": get_profile(row.exam)["label"] if row.exam else ""})
    return out


def progress_for(user, course_id):
    """Progress dict for one learner in ONE course, or None (not enrolled / not tiered / no data)."""
    from .models import StudentTier

    if not course_id or not is_enrolled(user, course_id):
        return None
    row = StudentTier.objects.filter(user=user, course_id=course_id).first()
    if row is None and exam_for_course(course_id):
        try:  # first visit before any grade event: compute now
            from .service import compute_and_save
            row = compute_and_save(user, course_id)
        except Exception:  # never break the learner's page because of the model
            row = None
    if row is None:
        return None
    return build_progress(
        exam=row.exam, features=row.features, subject_scores=row.subject_scores,
        updated_at=row.updated_at, course_id=row.course_id, tier=row.tier,
        show_tier=getattr(settings, "TIER_SHOW_TO_LEARNERS", False),
        score=row.score, model_version=row.model_version, explanation=row.explanation,
    )

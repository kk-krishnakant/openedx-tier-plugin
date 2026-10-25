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


def _days_since_active(recency_score):
    if not recency_score or recency_score <= 0:
        return None
    return int(round(-14.0 * math.log(min(recency_score, 1.0))))


def _note(level, title, text):
    return {"level": level, "title": title, "text": text}


def build_progress(*, exam, features, subject_scores, updated_at=None, course_id="", tier=None, show_tier=False):
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
    return out


def progress_for(user, course_id=""):
    """Progress dict for one learner, or None if the course is not tiered / has no data."""
    from .models import StudentTier

    qs = StudentTier.objects.filter(user=user)
    row = qs.filter(course_id=course_id).first() if course_id else qs.order_by("-updated_at").first()
    if row is None and course_id and exam_for_course(course_id):
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
    )

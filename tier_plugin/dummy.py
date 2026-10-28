"""Pretend learners for testing. Each persona is a made-up study pattern, not a real person.

simulate() returns the same raw inputs that features.compute_features() takes, so a dummy learner
goes through exactly the same feature maths and model as a real one.
"""
import random
from datetime import datetime, timedelta, timezone

from .exams import get_profile

ENROLLED_DAYS = 49  # 7 weeks of an 8-week course

# base/slope: quiz % and its change per quiz. act_p: chance of studying on a day. decay: how much act_p
# falls over the course. until/from_day: days with activity. attempt_p: chance a subject quiz is taken.
# content_p: share of videos/reading pages completed. strong_n: only the first N subjects (strong persona). retry: share of problems tried more than once.
PERSONAS = {
    "steady_topper": dict(content_p=0.92, base=85, slope=0.2, noise=6, act_p=0.80, attempt_p=0.97, retry=0.55),
    "consistent_average": dict(content_p=0.62, base=62, slope=0.2, noise=9, act_p=0.60, attempt_p=0.90, retry=0.40),
    "fast_improver": dict(content_p=0.5, base=38, slope=2.4, noise=7, act_p=0.55, attempt_p=0.90, retry=0.60),
    "slipping": dict(content_p=0.45, base=78, slope=-1.8, noise=7, act_p=0.65, decay=0.8, attempt_p=0.85, retry=0.25),
    "struggling": dict(content_p=0.15, base=32, slope=0.1, noise=9, act_p=0.35, attempt_p=0.60, retry=0.15),
    "crammer": dict(content_p=0.5, base=60, slope=0.0, noise=10, act_p=0.85, from_day=35, attempt_p=0.85, retry=0.30, cram=True),
    "early_dropout": dict(content_p=0.2, base=58, slope=-1.0, noise=9, act_p=0.65, until=14, attempt_p=0.90, retry=0.30),
    "narrow_specialist": dict(content_p=0.4, base=82, slope=0.0, noise=6, act_p=0.55, attempt_p=1.0, retry=0.40, strong_n=3),
    "new_joiner": dict(content_p=0.0, base=0, slope=0, noise=0, act_p=0.0, attempt_p=0.0, retry=0.0, enrolled=3),
}


def _clip(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def simulate(exam, persona, seed, now=None):
    """Returns dict(enrolled_at, subsection_rows, activity_days, problem_attempts, total_graded, subjects)."""
    p = PERSONAS[persona]
    rng = random.Random("%s|%s|%s" % (exam, persona, seed))
    now = now or datetime.now(timezone.utc)
    subjects = get_profile(exam)["subjects"]
    n_days = p.get("enrolled", ENROLLED_DAYS)
    first, last = p.get("from_day", 0), p.get("until", n_days)  # day numbers counted from enrolment

    active = set()
    for d in range(first, min(last, n_days)):
        prob = p["act_p"] * (1 - p.get("decay", 0.0) * d / ENROLLED_DAYS)
        if rng.random() < prob:
            active.add(d)

    pool = subjects[: p["strong_n"]] if p.get("strong_n") else subjects
    rows, attempts, idx = [], [], 0
    for i, name in enumerate(subjects):
        if name not in pool or rng.random() > p["attempt_p"] or not active:
            continue
        if p.get("cram"):
            day = rng.choice(sorted(active))
        else:
            due = int(i * (ENROLLED_DAYS - 14) / max(1, len(subjects) - 1))  # quizzes spread over weeks 1-6
            later = [d for d in sorted(active) if d >= due]
            day = later[0] if later else None
        if day is None:
            continue
        pct = _clip(p["base"] + p["slope"] * idx + rng.gauss(0, p["noise"]))
        rows.append({"when": now - timedelta(days=n_days - day), "earned": round(pct / 10, 1), "possible": 10.0,
                     "name": "%s: Practice Quiz" % name})
        for _ in range(8):  # the 8 problems of that quiz: 1 attempt, or 2-3 if retried
            attempts.append(rng.choice([2, 3]) if rng.random() < p["retry"] else 1)
        idx += 1
    # videos and reading pages: 30 videos + 30 pages in the dummy course; completion follows content_p
    total_video, total_pages = 30, 30
    pace = max(0.0, min(1.0, p["content_p"] + rng.uniform(-0.08, 0.08))) if p["content_p"] else 0.0
    done_video = round(total_video * max(0.0, min(1.0, pace * rng.uniform(0.7, 1.0))))
    done_pages = round(total_pages * pace)
    today = now.date()
    return dict(
        enrolled_at=now - timedelta(days=n_days),
        subsection_rows=rows,
        activity_days={today - timedelta(days=n_days - d) for d in active},
        problem_attempts=attempts,
        total_graded=len(subjects) + 2,  # one quiz per subject plus two mock tests
        content_blocks=(done_video + done_pages, total_video + total_pages, done_video, total_video),
        subjects=subjects,
    )


def persona_cycle(count):
    """Spread count learners over the personas (new_joiner is rarer)."""
    names = [n for n in PERSONAS if n != "new_joiner"]
    out = [names[i % len(names)] for i in range(count)]
    if count >= 10:
        out[-1] = "new_joiner"
    return out

from django.conf import settings
from django.core.cache import cache

from .exams import exam_for_course


def on_grade_changed(sender, user=None, course_key=None, **kwargs):
    """Runs whenever a learner's course grade is recalculated.

    Only courses listed in TIER_COURSE_EXAMS are handled. Schedules one tier update a little
    later; further changes in that window are skipped, so a burst of grade updates causes one
    model call, computed on the final data."""
    if user is None or course_key is None or exam_for_course(course_key) is None:
        return
    from .tasks import compute_tier_task

    delay = getattr(settings, "TIER_DEBOUNCE_SECONDS", 60)
    lock = "tier_plugin:pending:%s:%s" % (user.id, course_key)
    if cache.add(lock, 1, delay + 30):  # add() only succeeds for the first caller
        compute_tier_task.apply_async(args=[user.id, str(course_key)], countdown=delay)

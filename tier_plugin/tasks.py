import logging

from celery import shared_task

log = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def compute_tier_task(user_id, course_id):
    from django.contrib.auth import get_user_model
    from opaque_keys.edx.keys import CourseKey

    from .service import compute_and_save

    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    obj = compute_and_save(user, CourseKey.from_string(course_id))
    log.info("tier_plugin: user=%s course=%s tier=%s", user_id, course_id, obj.tier)

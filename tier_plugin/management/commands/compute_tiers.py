from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Compute tiers for every active learner in a course (first run / backfill / re-run after a model change)."

    def add_arguments(self, parser):
        parser.add_argument("--course-id", required=True, help="e.g. course-v1:TestOrg+GATE101+2026")

    def handle(self, *args, **options):
        from common.djangoapps.student.models import CourseEnrollment
        from opaque_keys import InvalidKeyError
        from opaque_keys.edx.keys import CourseKey

        from tier_plugin.exams import exam_for_course
        from tier_plugin.service import compute_and_save

        try:
            key = CourseKey.from_string(options["course_id"])
        except InvalidKeyError:
            raise CommandError("Invalid course id: %s" % options["course_id"])
        if exam_for_course(key) is None:
            raise CommandError("%s is not listed in TIER_COURSE_EXAMS (see README)." % key)

        done = failed = 0
        for enrollment in CourseEnrollment.objects.filter(course_id=key, is_active=True).select_related("user"):
            try:
                compute_and_save(enrollment.user, key)
                done += 1
            except Exception as exc:  # keep going, report at the end
                failed += 1
                self.stderr.write("user %s failed: %s" % (enrollment.user_id, exc))
        self.stdout.write("Done: %d updated, %d failed." % (done, failed))

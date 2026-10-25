import csv
import hashlib
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Write one row of model inputs per learner to a CSV, to train or validate your model. "
        "Names and emails are not exported. Fill the empty 'outcome' column later with the real result "
        "(for example the learner's actual exam result) and join on learner_id."
    )

    def add_arguments(self, parser):
        parser.add_argument("--course-id", required=True)
        parser.add_argument("--out", required=True, help="CSV file to write")

    def handle(self, *args, **options):
        from common.djangoapps.student.models import CourseEnrollment
        from opaque_keys import InvalidKeyError
        from opaque_keys.edx.keys import CourseKey

        from tier_plugin import features as features_module
        from tier_plugin.exams import exam_for_course

        try:
            key = CourseKey.from_string(options["course_id"])
        except InvalidKeyError:
            raise CommandError("Invalid course id: %s" % options["course_id"])
        exam = exam_for_course(key)
        if exam is None:
            raise CommandError("%s is not listed in TIER_COURSE_EXAMS (see README)." % key)

        columns = ["learner_id", "exam"] + features_module.FEATURE_ORDER + ["subject_scores", "outcome"]
        count = 0
        with open(options["out"], "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for enrollment in CourseEnrollment.objects.filter(course_id=key, is_active=True).select_related("user"):
                feats, subjects = features_module.collect_features(enrollment.user, key, exam)
                # Stable pseudonymous id: the same learner always gets the same id on this site.
                learner_id = hashlib.sha256(
                    ("%s:%s" % (settings.SECRET_KEY, enrollment.user_id)).encode()
                ).hexdigest()[:16]
                writer.writerow(
                    [learner_id, exam]
                    + [round(feats[name], 6) for name in features_module.FEATURE_ORDER]
                    + [json.dumps(subjects), ""]
                )
                count += 1
        self.stdout.write("Wrote %d rows to %s" % (count, options["out"]))

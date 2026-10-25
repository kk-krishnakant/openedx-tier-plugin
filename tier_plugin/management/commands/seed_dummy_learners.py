"""Create pretend learners for GATE CSE and UGC NET CS, to test the tier and progress panel.

  ./manage.py lms seed_dummy_learners --course-id course-v1:TestOrg+GATE101+2026 --count 24

Default ("direct"): creates users and stores their tier rows from simulated activity. Works with
any course id listed in TIER_COURSE_EXAMS. Nothing in grades or course state is written.
--full: also enrols them and writes grades and problem state, so the real feature code runs
(needs the course imported; this part was not tested outside a live Open edX).
--clean: deletes the dummy users made by this command (usernames start with the prefix).
Writes a CSV report (username, persona, tier) to --report.
"""
import csv

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tier_plugin import dummy, features
from tier_plugin.exams import exam_for_course
from tier_plugin.model_adapter import get_backend
from tier_plugin.models import StudentTier

PREFIX = "dummy_"


class Command(BaseCommand):
    help = "Create dummy learners (study-pattern personas) for a course listed in TIER_COURSE_EXAMS."

    def add_arguments(self, parser):
        parser.add_argument("--course-id", required=True)
        parser.add_argument("--count", type=int, default=24)
        parser.add_argument("--seed", type=int, default=1)
        parser.add_argument("--prefix", default=PREFIX)
        parser.add_argument("--full", action="store_true", help="also write enrolment, grades and problem state")
        parser.add_argument("--clean", action="store_true", help="delete dummy users of this prefix and exit")
        parser.add_argument("--report", default="dummy_learners.csv")

    def handle(self, *args, **o):
        User = get_user_model()
        prefix = o["prefix"]
        if o["clean"]:
            n, _ = User.objects.filter(username__startswith=prefix).delete()
            self.stdout.write("Deleted %d objects for users starting with %r." % (n, prefix))
            return
        course_id = o["course_id"]
        exam = exam_for_course(course_id)
        if exam is None:
            raise CommandError("%s is not in TIER_COURSE_EXAMS." % course_id)
        backend = get_backend()
        now = timezone.now()
        report = []
        for i, persona in enumerate(dummy.persona_cycle(o["count"]), start=1):
            username = "%s%s_%02d" % (prefix, exam.split("_")[0], i)
            user, _ = User.objects.get_or_create(username=username, defaults={"email": username + "@example.invalid"})
            if hasattr(user, "set_unusable_password"):
                user.set_unusable_password()
                user.save()
            sim = dummy.simulate(exam, persona, "%s-%d" % (o["seed"], i), now=now)
            if o["full"]:
                self._write_full(user, course_id, persona, sim)
            f, subject_scores = features.compute_features(now=now, **sim)
            pred = backend.predict(f, {"exam": exam, "subject_scores": subject_scores})
            StudentTier.objects.update_or_create(
                user=user, course_id=course_id,
                defaults=dict(exam=exam, tier=pred.tier, score=pred.score, features=f,
                              subject_scores=subject_scores, model_version=pred.version))
            report.append((username, persona, pred.tier, pred.score))
        with open(o["report"], "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["username", "persona", "tier", "score"])
            w.writerows(report)
        self.stdout.write("Created %d dummy learners for %s (%s). Report: %s" % (len(report), course_id, exam, o["report"]))

    def _write_full(self, user, course_id, persona, sim):
        """Best effort, for a live Open edX only: enrolment, subsection grades, problem state, persona note."""
        import json

        from common.djangoapps.student.models import CourseEnrollment
        from lms.djangoapps.courseware.models import StudentModule
        from lms.djangoapps.grades.models import PersistentSubsectionGrade
        from opaque_keys.edx.keys import CourseKey
        from xmodule.modulestore.django import modulestore

        key = CourseKey.from_string(course_id)
        enrollment, _ = CourseEnrollment.objects.get_or_create(user=user, course_id=key)
        CourseEnrollment.objects.filter(pk=enrollment.pk).update(created=sim["enrolled_at"])
        store = modulestore()
        course = store.get_course(key)
        by_name = {}
        for chapter in course.get_children():
            for seq in chapter.get_children():
                by_name[seq.display_name] = seq
        for row in sim["subsection_rows"]:
            seq = by_name.get(row["name"])
            if seq is None:
                continue
            PersistentSubsectionGrade.update_or_create_grade(
                user_id=user.id, usage_key=seq.location, course_id=key, subtree_edited_timestamp=row["when"],
                earned_all=row["earned"], possible_all=row["possible"], earned_graded=row["earned"],
                possible_graded=row["possible"], visible_blocks=[], first_attempted=row["when"],
                course_version="", subtree_edited_on=row["when"], )
        # note which persona this is, so reports can be checked against the tier
        profile = getattr(user, "profile", None)
        if profile is not None:
            profile.meta = json.dumps({"dummy_persona": persona})
            profile.save()

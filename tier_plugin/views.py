from django.conf import settings
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import StudentTier
from .progress import courses_for, progress_for


class MyTierView(APIView):
    """GET /api/tier/v1/me/?course_id=...  -> the logged-in learner's own tier."""

    authentication_classes = (JwtAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        if not getattr(settings, "TIER_SHOW_TO_LEARNERS", False):
            return Response({"detail": "Tier display is turned off."}, status=403)
        course_id = request.query_params.get("course_id")
        if not course_id:
            return Response({"detail": "course_id is required."}, status=400)
        row = StudentTier.objects.filter(user=request.user, course_id=course_id).first()
        if row is None:
            return Response({"detail": "No tier yet."}, status=404)
        return Response({
            "course_id": row.course_id,
            "exam": row.exam,
            "tier": row.tier,
            "subject_scores": row.subject_scores,
            "updated_at": row.updated_at,
        })


class MyProgressView(APIView):
    """GET /api/tier/v1/me/progress/?course_id=...  -> the learner's own progress and notifications.
    The tier is included only when TIER_SHOW_TO_LEARNERS is True."""

    authentication_classes = (JwtAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        course_id = request.query_params.get("course_id", "")
        if not course_id:
            return Response({"detail": "course_id is required (progress is shown per course)."}, status=400)
        data = progress_for(request.user, course_id)
        if data is None:
            return Response({"detail": "No progress yet."}, status=404)
        return Response(data)


class MyCoursesView(APIView):
    """GET /api/tier/v1/me/courses/  -> the learner's own enrolled courses that have progress."""

    authentication_classes = (JwtAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response({"courses": courses_for(request.user)})


class CourseTiersView(APIView):
    """GET /api/tier/v1/courses/<course_id>/  -> every learner's tier, for course staff only."""

    authentication_classes = (JwtAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request, course_id):
        from common.djangoapps.student.roles import CourseInstructorRole, CourseStaffRole
        from opaque_keys import InvalidKeyError
        from opaque_keys.edx.keys import CourseKey

        try:
            key = CourseKey.from_string(course_id)
        except InvalidKeyError:
            return Response({"detail": "Invalid course id."}, status=400)
        user = request.user
        allowed = user.is_staff or CourseStaffRole(key).has_user(user) or CourseInstructorRole(key).has_user(user)
        if not allowed:
            return Response({"detail": "Course staff only."}, status=403)
        rows = StudentTier.objects.filter(course_id=str(key)).select_related("user")
        results = [
            {
                "username": r.user.username,
                "exam": r.exam,
                "tier": r.tier,
                "score": r.score,
                "model_version": r.model_version,
                "features": r.features,
                "subject_scores": r.subject_scores,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]
        return Response({"count": len(results), "results": results})

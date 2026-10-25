from django.contrib import admin

from .models import StudentTier


@admin.register(StudentTier)
class StudentTierAdmin(admin.ModelAdmin):
    list_display = ("user", "course_id", "exam", "tier", "score", "model_version", "updated_at")
    list_filter = ("exam", "tier", "course_id")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("features", "subject_scores", "updated_at")

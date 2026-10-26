from django.conf import settings
from django.db import models


class StudentTier(models.Model):
    """The latest tier given to one learner in one course."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    course_id = models.CharField(max_length=255, db_index=True)
    exam = models.CharField(max_length=32, blank=True, default="")
    tier = models.CharField(max_length=32)
    score = models.FloatField(null=True, blank=True)
    # The exact inputs the model saw, so every tier can be explained later.
    features = models.JSONField(default=dict)
    subject_scores = models.JSONField(default=dict)
    # Per-feature impact on the score (SHAP values from your model, or the composite breakdown).
    explanation = models.JSONField(default=list, blank=True)
    model_version = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("user", "course_id"),)

    def __str__(self):
        return "%s | %s | %s" % (self.user_id, self.course_id, self.tier)

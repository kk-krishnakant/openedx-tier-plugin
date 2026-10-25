import logging

from django.apps import AppConfig

log = logging.getLogger(__name__)


class TierPluginConfig(AppConfig):
    name = "tier_plugin"
    verbose_name = "Student Tier"
    default_auto_field = "django.db.models.BigAutoField"

    # Read by Open edX's plugin framework.
    plugin_app = {
        "url_config": {
            "lms.djangoapp": {
                "namespace": "tier_plugin",
                "regex": r"^api/tier/",
                "relative_path": "urls",
            }
        },
        "settings_config": {
            "lms.djangoapp": {
                "common": {"relative_path": "settings.common"},
            }
        },
    }

    def ready(self):
        # The signal is connected here (not in plugin_app) on purpose: if the
        # import path differs on your Open edX version, the LMS still starts and
        # you only lose automatic updates (the compute_tiers command still works).
        try:
            from openedx.core.djangoapps.signals.signals import COURSE_GRADE_CHANGED
        except ImportError:
            log.warning("tier_plugin: COURSE_GRADE_CHANGED not found, automatic tier updates are off.")
            return
        from . import signals

        COURSE_GRADE_CHANGED.connect(
            signals.on_grade_changed, dispatch_uid="tier_plugin_on_grade_changed"
        )

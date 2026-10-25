from setuptools import find_packages, setup

setup(
    name="openedx-tier-plugin",
    version="0.3.0",
    description="Open edX plugin that assigns each learner a tier using your own model.",
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    install_requires=["requests"],
    # This entry point is what makes Open edX load the app (LMS only).
    entry_points={
        "lms.djangoapp": [
            "tier_plugin = tier_plugin.apps:TierPluginConfig",
        ],
    },
)

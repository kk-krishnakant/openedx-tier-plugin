"""Which exam a course prepares for, and that exam's subjects.

A subject is matched to a graded subsection by name: a subsection called
"Operating Systems: Practice Quiz" counts as the subject "Operating Systems".
Keep subsection names starting with the subject name below (or edit the lists).
Check the lists against the current official syllabus before using them for real.
"""
from django.conf import settings

DEFAULT_EXAM_PROFILES = {
    "gate_cse": {
        "label": "GATE Computer Science and Information Technology",
        "subjects": [
            "Discrete Mathematics",
            "Linear Algebra",
            "Probability and Calculus",
            "Digital Logic",
            "Programming in C",
            "Data Structures",
            "Algorithms",
            "Theory of Computation",
            "Compiler Design",
            "Computer Organization and Architecture",
            "Operating Systems",
            "Database Management Systems",
            "Computer Networks",
            "General Aptitude",
        ],
    },
    "ugc_net_cs": {
        "label": "UGC NET Computer Science and Applications",
        "subjects": [
            "Teaching and Research Aptitude",
            "Paper 1 Reasoning and Data Interpretation",
            "Discrete Structures and Optimization",
            "Computer System Architecture",
            "Programming Languages and Computer Graphics",
            "Database Management Systems",
            "System Software and Operating System",
            "Software Engineering",
            "Data Structures and Algorithms",
            "Theory of Computation and Compilers",
            "Data Communication and Computer Networks",
            "Artificial Intelligence",
        ],
    },
}


def get_profile(exam):
    profiles = getattr(settings, "TIER_EXAM_PROFILES", None) or DEFAULT_EXAM_PROFILES
    return profiles[exam]


def exam_for_course(course_key):
    """Returns e.g. "gate_cse" for a course listed in TIER_COURSE_EXAMS, else None.
    Courses that are not listed are never tiered."""
    return (getattr(settings, "TIER_COURSE_EXAMS", None) or {}).get(str(course_key))

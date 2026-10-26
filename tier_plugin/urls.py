from django.urls import re_path

from .pages import progress_page
from .views import CourseTiersView, MyCoursesView, MyProgressView, MyTierView

# Same shape Open edX uses for course ids: course-v1:Org+Course+Run
COURSE_ID = r"(?P<course_id>[^/+]+(/|\+)[^/+]+(/|\+)[^/?]+)"

urlpatterns = [
    re_path(r"^progress/$", progress_page, name="progress_page"),
    re_path(r"^v1/me/courses/$", MyCoursesView.as_view(), name="my_courses"),
    re_path(r"^v1/me/progress/$", MyProgressView.as_view(), name="my_progress"),
    re_path(r"^v1/me/$", MyTierView.as_view(), name="me"),
    re_path(r"^v1/courses/%s/$" % COURSE_ID, CourseTiersView.as_view(), name="course"),
]

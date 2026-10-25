from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from .widget import PAGE_HTML


@login_required
def progress_page(request):
    """GET /api/tier/progress/  -> the learner's progress page (works with ?course_id=...)."""
    return HttpResponse(PAGE_HTML, content_type="text/html; charset=utf-8")

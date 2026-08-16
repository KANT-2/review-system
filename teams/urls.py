from django.conf import settings
from django.urls import path

from teams import views

app_name = "teams"

urlpatterns = [
    path("student/", views.student_team_page, name="student-page"),
    path("student/team/", views.student_team_view, name="student-team"),
    path(
        "manage/rounds/<int:round_id>/",
        views.management_team_page,
        name="management-page",
    ),
    path(
        "manage/rounds/<int:round_id>/teams/",
        views.management_team_view,
        name="management-team",
    ),
    path(
        "manage/rounds/<int:round_id>/teams/auto/",
        views.auto_assignment_view,
        name="auto-assignment",
    ),
    path(
        "manage/rounds/<int:round_id>/teams/save/",
        views.save_team_view,
        name="save-team",
    ),
]

if settings.DEBUG:
    urlpatterns.insert(0, path("preview/", views.team_ui_preview, name="ui-preview"))

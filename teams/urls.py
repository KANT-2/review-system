from django.urls import path

from teams import views

app_name = "teams"

urlpatterns = [
    path("student/team/", views.student_team_view, name="student-team"),
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

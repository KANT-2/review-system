from django.urls import path

from results import views as result_views
from rounds import views
from teams import views as team_views

app_name = "rounds"

urlpatterns = [
    path("", views.operations_dashboard, name="dashboard"),
    path("rounds/", views.round_list, name="list"),
    path("rounds/new/", views.round_edit, name="create"),
    path("rounds/<int:round_id>/", views.round_edit, name="edit"),
    path("rounds/<int:round_id>/start/", views.round_start, name="start"),
    path("rounds/<int:round_id>/reviews/", views.round_reviews, name="reviews"),
    path("rounds/<int:round_id>/complete/", views.round_complete, name="complete"),
    path("rounds/<int:round_id>/teams/", team_views.management_team_page, name="teams"),
    path("rounds/<int:round_id>/results/", result_views.manage_results, name="results"),
    path(
        "rounds/<int:round_id>/results/calculate/",
        result_views.calculate,
        name="calculate-results",
    ),
    path(
        "rounds/<int:round_id>/results/publish/<str:item_key>/",
        result_views.publish,
        name="publish-results",
    ),
    path(
        "rounds/<int:round_id>/results/publish-all/",
        result_views.publish_all,
        name="publish-all-results",
    ),
    path(
        "rounds/<int:round_id>/results/notes/<int:participant_id>/",
        result_views.save_note,
        name="save-student-note",
    ),
]

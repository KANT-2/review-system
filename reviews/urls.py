from django.urls import path

from reviews import views

app_name = "reviews"

urlpatterns = [
    path("", views.review_home, name="home"),
    path("teams/", views.team_review_list, name="team-list"),
    path("teams/<int:target_id>/", views.team_review_form, name="team-form"),
    path("peers/", views.peer_review_list, name="peer-list"),
    path("peers/<int:target_id>/", views.peer_review_form, name="peer-form"),
    path("peers/<int:target_id>/lock/", views.peer_review_lock, name="peer-lock"),
    path("status/", views.review_status, name="status"),
    path(
        "final-submit/<str:review_type>/",
        views.review_final_submit,
        name="final-submit",
    ),
    path(
        "submissions/<int:submission_id>/",
        views.submission_detail,
        name="submission-detail",
    ),
]

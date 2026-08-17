from django.urls import path

from reviews import views

app_name = "reviews"

urlpatterns = [
    path("teams/", views.team_review_list, name="team-list"),
    path("teams/<int:target_id>/", views.team_review_form, name="team-form"),
    path("peers/", views.peer_review_list, name="peer-list"),
    path("peers/<int:target_id>/", views.peer_review_form, name="peer-form"),
    path("status/", views.review_status, name="status"),
]

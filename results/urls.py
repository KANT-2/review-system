from django.urls import path

from results import views

app_name = "results"

urlpatterns = [
    path("me/", views.my_results, name="me"),
    path("manage/<int:round_id>/", views.manage_results, name="manage"),
    path("manage/<int:round_id>/calculate/", views.calculate, name="calculate"),
    path(
        "manage/<int:round_id>/publish/<str:item_key>/",
        views.publish,
        name="publish",
    ),
]

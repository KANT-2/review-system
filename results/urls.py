from django.urls import path

from results import views

app_name = "results"

urlpatterns = [
    path("preview/manage/", views.manage_preview, name="manage_preview"),
    path("preview/me/", views.me_preview, name="me_preview"),
]

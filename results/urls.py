from django.urls import path

from results import views

app_name = "results"

urlpatterns = [
    path("preview/manage/", views.manage_preview, name="manage_preview"),
    path("preview/me/", views.me_preview, name="me_preview"),
    path(
        "preview/publish/all/toggle/",
        views.toggle_publish_all,
        name="toggle_publish_all",
    ),
    path(
        "preview/publish/<str:item_key>/toggle/",
        views.toggle_publish,
        name="toggle_publish",
    ),
    path(
        "preview/publish/cancel/",
        views.cancel_publish_confirm,
        name="cancel_publish_confirm",
    ),
    path(
        "preview/notes/save/",
        views.save_student_note,
        name="save_student_note",
    ),
]

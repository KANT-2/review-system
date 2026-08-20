from django.urls import path

from notices import views

app_name = "notices"

urlpatterns = [
    path("", views.portal, name="portal"),
    path("<int:notice_id>/detail.json", views.notice_detail_json, name="notice-detail-json"),
    path("new/", views.notice_create, name="notice-create"),
    path("<int:notice_id>/edit/", views.notice_edit, name="notice-edit"),
    path("<int:notice_id>/delete/", views.notice_delete, name="notice-delete"),
    path(
        "<int:notice_id>/toggle/",
        views.notice_toggle_publish,
        name="notice-toggle-publish",
    ),
]

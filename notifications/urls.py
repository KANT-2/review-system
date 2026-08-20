from django.urls import path

from notifications import views

app_name = "notifications"

urlpatterns = [
    path("summary/", views.summary, name="summary"),
    path("<int:notification_id>/read/", views.mark_read_view, name="mark-read"),
    path("mark-all-read/", views.mark_all_read_view, name="mark-all-read"),
    path("<int:notification_id>/delete/", views.delete_view, name="delete"),
    path("delete-all/", views.delete_all_view, name="delete-all"),
]

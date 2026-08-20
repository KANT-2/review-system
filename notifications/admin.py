from django.contrib import admin

from accounts.admin_permissions import OperationsReadOnlyAdminMixin
from notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(OperationsReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("recipient", "category", "title", "created_at", "read_at")
    list_filter = ("category",)
    search_fields = ("title", "message", "recipient__email")
    readonly_fields = ("created_at",)

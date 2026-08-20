from django.contrib import admin

from accounts.admin_permissions import OperationsReadOnlyAdminMixin
from audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(OperationsReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "action", "target_type", "target_id", "actor", "result")
    list_filter = ("action", "result")
    search_fields = ("target_id", "actor__email")
    readonly_fields = (
        "round",
        "actor",
        "action",
        "target_type",
        "target_id",
        "result",
        "summary",
        "request_id",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

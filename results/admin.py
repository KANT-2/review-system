from django.contrib import admin

from accounts.admin_permissions import OperationsReadOnlyAdminMixin
from results.models import CalculationRun, EvaluationResult


class ReadOnlyAdmin(OperationsReadOnlyAdminMixin, admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CalculationRun)
class CalculationRunAdmin(ReadOnlyAdmin):
    list_display = ("round", "version", "status", "is_active", "executed_by", "finished_at")
    list_filter = ("status", "is_active")


@admin.register(EvaluationResult)
class EvaluationResultAdmin(ReadOnlyAdmin):
    list_display = (
        "calculation_run",
        "result_type",
        "team",
        "participant",
        "display_score",
        "primary_rank",
        "data_status",
    )
    list_filter = ("result_type", "data_status")

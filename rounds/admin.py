from django.contrib import admin

from rounds.models import EvaluationRound, QuestionTemplate, RoundParticipant, TemplateQuestion


class TemplateQuestionInline(admin.TabularInline):
    model = TemplateQuestion
    extra = 1

    def has_change_permission(self, request, obj=None):
        return not obj or not obj.is_locked

    def has_delete_permission(self, request, obj=None):
        return not obj or not obj.is_locked


@admin.register(QuestionTemplate)
class QuestionTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "created_by", "created_at", "locked")
    list_filter = ("category",)
    search_fields = ("name",)
    readonly_fields = ("created_by", "created_at", "updated_at")
    inlines = (TemplateQuestionInline,)

    @admin.display(boolean=True, description="사용 중")
    def locked(self, obj):
        return obj.is_locked

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (not obj or not obj.is_locked)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (not obj or not obj.is_locked)


@admin.register(EvaluationRound)
class EvaluationRoundAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "evaluation_start_at", "evaluation_end_at")
    list_filter = ("status",)
    readonly_fields = ("status", "started_at", "completed_at", "lock_version")


@admin.register(RoundParticipant)
class RoundParticipantAdmin(admin.ModelAdmin):
    list_display = ("round", "student_number_snapshot", "display_name_snapshot")
    readonly_fields = ("round", "user", "student_number_snapshot", "display_name_snapshot")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.round.status == EvaluationRound.Status.DRAFT)

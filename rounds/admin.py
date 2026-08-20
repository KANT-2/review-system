from django.contrib import admin, messages

from accounts.admin_permissions import (
    OperationsAdminMixin,
    OperationsReadOnlyAdminMixin,
)
from rounds.models import EvaluationRound, QuestionTemplate, RoundParticipant, TemplateQuestion
from rounds.services import pending_participant_rows


def _round_recipient_emails(round_obj):
    return list(
        round_obj.participants.filter(user__is_active=True)
        .exclude(user__email="")
        .values_list("user__email", flat=True)
    )


class TemplateQuestionInline(OperationsAdminMixin, admin.TabularInline):
    model = TemplateQuestion
    extra = 1

    def has_change_permission(self, request, obj=None):
        return not obj or not obj.is_locked

    def has_delete_permission(self, request, obj=None):
        return not obj or not obj.is_locked


@admin.register(QuestionTemplate)
class QuestionTemplateAdmin(OperationsAdminMixin, admin.ModelAdmin):
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
class EvaluationRoundAdmin(OperationsAdminMixin, admin.ModelAdmin):
    list_display = ("title", "status", "evaluation_start_at", "evaluation_end_at")
    list_filter = ("status",)
    readonly_fields = ("status", "started_at", "completed_at", "lock_version")
    actions = ["send_round_started_mail", "send_results_released_mail", "send_submission_reminders"]

    @admin.action(description="선택한 회차 참가자에게 평가 시작 안내 메일 발송")
    def send_round_started_mail(self, request, queryset):
        from accounts.email_services import send_round_started_email

        total_sent = 0
        for round_obj in queryset.filter(status=EvaluationRound.Status.IN_PROGRESS):
            total_sent += send_round_started_email(round_obj, _round_recipient_emails(round_obj))
        self.message_user(
            request,
            f"회차 참가자들에게 총 {total_sent}건의 평가 개시 알림 메일이 발송되었습니다.",
            messages.SUCCESS,
        )

    @admin.action(description="선택한 회차 참가자에게 성적 공개 안내 메일 발송")
    def send_results_released_mail(self, request, queryset):
        from accounts.email_services import send_results_released_email

        total_sent = 0
        for round_obj in queryset.filter(status=EvaluationRound.Status.COMPLETED):
            total_sent += send_results_released_email(round_obj, _round_recipient_emails(round_obj))
        self.message_user(
            request,
            f"회차 참가자들에게 총 {total_sent}건의 성적 공개 알림 메일이 발송되었습니다.",
            messages.SUCCESS,
        )

    @admin.action(description="선택한 회차 미제출자에게 제출 안내 메일 발송")
    def send_submission_reminders(self, request, queryset):
        from accounts.email_services import send_submission_reminder_email

        total_sent = 0
        for round_obj in queryset.filter(status=EvaluationRound.Status.IN_PROGRESS):
            for row in pending_participant_rows(round_obj):
                student = row["participant"].user
                if not student.is_active or not student.email:
                    continue
                name = student.first_name if student.first_name else student.email
                send_submission_reminder_email(round_obj, name, student.email)
                total_sent += 1
        self.message_user(
            request,
            f"미제출 참가자들에게 총 {total_sent}건의 제출 안내 메일이 발송되었습니다.",
            messages.SUCCESS,
        )


@admin.register(RoundParticipant)
class RoundParticipantAdmin(OperationsReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("round", "student_number_snapshot", "display_name_snapshot")
    readonly_fields = ("round", "user", "student_number_snapshot", "display_name_snapshot")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.round.status == EvaluationRound.Status.DRAFT)

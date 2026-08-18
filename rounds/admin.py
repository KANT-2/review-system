from django.contrib import admin, messages

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
    actions = ["send_round_started_mail", "send_results_released_mail", "send_submission_reminders"]

    @admin.action(description="🚀 선택한 회차 '평가 시작 안내' 이메일 수강생 전원 발송")
    def send_round_started_mail(self, request, queryset):
        from accounts.email_services import send_round_started_email
        from accounts.models import User
        student_emails = list(
            User.objects.filter(role=User.Role.STUDENT, is_active=True).values_list("email", flat=True)
        )
        total_sent = 0
        for round_obj in queryset:
            total_sent += send_round_started_email(round_obj, student_emails)
        self.message_user(request, f"수강생들에게 총 {total_sent}건의 평가 개시 알림 메일이 발송되었습니다.", messages.SUCCESS)

    @admin.action(description="👁️ 선택한 회차 '성적 및 피드백 공개' 이메일 수강생 전원 발송")
    def send_results_released_mail(self, request, queryset):
        from accounts.email_services import send_results_released_email
        from accounts.models import User
        student_emails = list(
            User.objects.filter(role=User.Role.STUDENT, is_active=True).values_list("email", flat=True)
        )
        total_sent = 0
        for round_obj in queryset:
            total_sent += send_results_released_email(round_obj, student_emails)
        self.message_user(request, f"수강생들에게 총 {total_sent}건의 성적 공개 알림 메일이 발송되었습니다.", messages.SUCCESS)

    @admin.action(description="⏰ 선택한 회차 '평가 미제출자' 독촉 이메일 발송")
    def send_submission_reminders(self, request, queryset):
        from django.contrib import messages

        from accounts.email_services import send_submission_reminder_email
        from accounts.models import User
        students = User.objects.filter(role=User.Role.STUDENT, is_active=True)
        total_sent = 0
        for round_obj in queryset:
            for student in students:
                name = student.first_name if student.first_name else student.email
                send_submission_reminder_email(round_obj, name, student.email)
                total_sent += 1
        self.message_user(request, f"미제출 수강생들에게 총 {total_sent}건의 제출 독촉 메일이 발송되었습니다.", messages.SUCCESS)



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

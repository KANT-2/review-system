from django.contrib import admin, messages

from accounts.admin_permissions import (
    OperationsAdminMixin,
    OperationsReadOnlyAdminMixin,
)
from rounds.models import EvaluationRound
from teams.models import Team, TeamMembership


class TeamMembershipInline(OperationsAdminMixin, admin.TabularInline):
    model = TeamMembership
    extra = 0
    readonly_fields = ("participant", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Team)
class TeamAdmin(OperationsAdminMixin, admin.ModelAdmin):
    list_display = ("round", "team_number", "name", "member_count")
    inlines = (TeamMembershipInline,)
    actions = ["send_announcement_to_team"]

    @admin.display(description="인원")
    def member_count(self, obj):
        return obj.memberships.count()

    @admin.action(description="선택한 조(팀) 팀원에게 공지 메일 발송")
    def send_announcement_to_team(self, request, queryset):
        from accounts.email_services import send_tutor_announcement_email

        total_sent = 0
        for team in queryset:
            student_emails = list(
                team.memberships.filter(participant__user__is_active=True)
                .exclude(participant__user__email="")
                .values_list("participant__user__email", flat=True)
            )
            if student_emails:
                sent = send_tutor_announcement_email(
                    subject=f"[{team.name}] 발표 평가 관련 안내드립니다.",
                    message=f"안녕하세요 {team.name} 팀원 여러분,\n튜터 공지사항입니다. 평가 일정을 다시 한 번 확인해 주시기 바랍니다.",
                    recipient_emails=student_emails,
                )
                total_sent += sent
        self.message_user(
            request,
            f"선택한 조 팀원들에게 총 {total_sent}건의 공지 이메일이 발송되었습니다.",
            messages.SUCCESS,
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(obj and obj.round.status == EvaluationRound.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TeamMembership)
class TeamMembershipAdmin(OperationsReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("team", "participant", "created_at")
    readonly_fields = ("team", "participant", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

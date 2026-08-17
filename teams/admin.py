from django.contrib import admin

from rounds.models import EvaluationRound
from teams.models import Team, TeamMembership


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0
    readonly_fields = ("participant", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("round", "team_number", "name", "member_count")
    inlines = (TeamMembershipInline,)

    @admin.display(description="인원")
    def member_count(self, obj):
        return obj.memberships.count()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(obj and obj.round.status == EvaluationRound.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("team", "participant", "created_at")
    readonly_fields = ("team", "participant", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

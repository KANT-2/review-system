from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.admin_permissions import AdminOnlyMixin
from accounts.models import AuthThrottleBucket, User, WhitelistEmail


@admin.register(User)
class AccountUserAdmin(AdminOnlyMixin, UserAdmin):
    ordering = ("email",)
    list_display = (
        "email",
        "first_name",
        "student_number",
        "role",
        "approval_status",
        "is_active",
    )
    search_fields = ("email", "first_name", "student_number")
    # is_staff는 역할이 정한다(User.save) - 손으로 고치면 DB 제약과 어긋난다.
    readonly_fields = ("auth_session_version", "email_needs_review", "is_staff")

    def get_readonly_fields(self, request, obj=None):
        """역할은 만들 때만 고른다.

        앱 화면에서 역할 변경을 걷어냈는데(권한 상승 경로를 남기지 않기 위해서다) 관리자
        화면에 남겨 두면 같은 경로가 그대로 있는 셈이다. 역할을 바꿔야 하면 계정을 다시
        만든다 - 튜터는 한 명이라 실제로 일어날 일이 아니다.
        """
        fields = super().get_readonly_fields(request, obj)
        if obj is not None:
            return (*fields, "role")
        return fields

    actions = ["send_custom_email_action"]

    @admin.action(description="선택한 수강생에게 공지 메일 발송")
    def send_custom_email_action(self, request, queryset):
        from django.contrib import messages

        from accounts.email_services import send_tutor_announcement_email

        recipient_emails = list(queryset.values_list("email", flat=True))
        sent = send_tutor_announcement_email(
            subject="AX 평가 시스템 튜터 개별 안내",
            message="안녕하세요, 튜터 공지사항입니다. 평가 일정 및 안내사항을 확인해 주세요.",
            recipient_emails=recipient_emails,
        )
        self.message_user(
            request, f"수강생에게 공지 메일 {sent}건을 발송했습니다.", messages.SUCCESS
        )

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "프로필",
            {"fields": ("first_name", "student_number", "phone_number")},
        ),
        (
            "권한과 상태",
            {
                "fields": (
                    "role",
                    "approval_status",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "must_rotate_password",
                    "auth_session_version",
                    "email_needs_review",
                )
            },
        ),
        ("Django 권한", {"fields": ("groups", "user_permissions")}),
        ("일시", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "role", "approval_status"),
            },
        ),
    )

    def has_module_permission(self, request):
        return request.user.is_authenticated and request.user.is_application_admin


@admin.register(WhitelistEmail)
class WhitelistEmailAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at")
    search_fields = ("email",)
    ordering = ("-created_at",)

    @staticmethod
    def _allowed(request):
        return request.user.is_authenticated and request.user.is_application_admin

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self._allowed(request) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return self._allowed(request) and super().has_delete_permission(request, obj)


@admin.register(AuthThrottleBucket)
class SecurityStateAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser and request.user.is_application_admin

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

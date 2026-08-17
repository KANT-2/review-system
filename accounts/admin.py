from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import AuthThrottleBucket, User, WhitelistEmail


@admin.register(User)
class AccountUserAdmin(UserAdmin):
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
    readonly_fields = ("auth_session_version", "email_needs_review")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "프로필",
            {"fields": ("first_name", "student_number", "phone_number", "session_info")},
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
    list_display = ("email", "session_info", "created_at")
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

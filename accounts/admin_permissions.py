"""Django 관리자 화면에서 튜터에게 열어 줄 범위.

튜터도 운영 담당자라 관리자 화면을 쓴다(User.STAFF_ROLES). 다만 staff라는 것만으로는
Django가 아무 모델도 보여주지 않으므로, 모델마다 누가 무엇을 할 수 있는지 여기서 정한다.

권한을 auth 그룹 대신 코드로 두는 이유: 규칙이 화면 정의 옆에 남아 리뷰에서 보이고,
운영 중 그룹이 바뀌어 조용히 어긋나는 일이 없기 때문이다.
"""

from accounts.permissions import is_operations_user


class OperationsAdminMixin:
    """튜터·관리자가 보고 고칠 수 있는 화면.

    삭제는 관리자에게만 연다 - 회차·팀 삭제는 앱 화면의 서비스가 자식 기록 정리와 감사
    로그까지 맡고 있어서, 관리자 화면에서 직접 지우면 그 절차를 건너뛴다.
    """

    def has_module_permission(self, request):
        return is_operations_user(request.user)

    def has_view_permission(self, request, obj=None):
        return is_operations_user(request.user)

    def has_add_permission(self, request, obj=None):
        return is_operations_user(request.user)

    def has_change_permission(self, request, obj=None):
        return is_operations_user(request.user)

    def has_delete_permission(self, request, obj=None):
        return bool(getattr(request.user, "is_application_admin", False))


class OperationsReadOnlyAdminMixin(OperationsAdminMixin):
    """제출 기록·감사 로그처럼 사람이 손대면 안 되는 화면 - 보기만 연다."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AdminOnlyMixin:
    """계정·보안 기록처럼 관리자만 다루는 화면."""

    def has_module_permission(self, request):
        return bool(getattr(request.user, "is_application_admin", False))

    def has_view_permission(self, request, obj=None):
        return bool(getattr(request.user, "is_application_admin", False))

    def has_add_permission(self, request, obj=None):
        return bool(getattr(request.user, "is_application_admin", False))

    def has_change_permission(self, request, obj=None):
        return bool(getattr(request.user, "is_application_admin", False))

    def has_delete_permission(self, request, obj=None):
        return bool(getattr(request.user, "is_application_admin", False))

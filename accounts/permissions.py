from accounts.models import User


def is_operations_user(user):
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.is_application_admin:
        return True
    return user.role == User.Role.TUTOR and user.approval_status == User.ApprovalStatus.APPROVED


def is_student_user(user):
    return (
        getattr(user, "is_authenticated", False)
        and user.is_active
        and user.role == User.Role.STUDENT
        and user.approval_status == User.ApprovalStatus.APPROVED
    )

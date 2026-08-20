from django.utils import timezone

from notifications.models import Notification

# 메일 템플릿이 있는 알림 종류. 마이페이지의 수신 설정도 이 목록으로 그린다.
# (본인 확인·비밀번호 재설정 메일은 알림 사건이 아니라 계정 보호용이라 여기 없고,
#  수신 설정과 무관하게 항상 발송된다.)
EMAIL_CAPABLE_CATEGORIES = (
    Notification.Category.NOTICE,
    Notification.Category.ROUND_STARTED,
    Notification.Category.SUBMISSION_REMINDER,
    Notification.Category.RESULTS_PUBLISHED,
)


def announce(users, *, category, title, message="", link="", email_sender=None):
    """하나의 사건을 종 알림과 메일 양쪽으로 내보낸다.

    두 채널을 각 호출부에서 따로 챙기면 "메일은 갔는데 알림은 없는" 사건이 생긴다
    (결과 공개가 그랬다). 사건마다 이 함수를 한 번만 부르는 것을 규칙으로 삼는다.

    ``email_sender``는 메일을 받을 사용자 목록을 받아 실제 발송을 맡는 함수다. 메일
    템플릿이 없는 종류(팀 배정 등)는 넘기지 않으면 종 알림만 나간다. 메일은 사용자가
    그 종류를 꺼두지 않은 경우에만 나가고, 종 알림은 설정과 무관하게 항상 남는다.
    """
    recipients = list(users)
    notify_users(recipients, category=category, title=title, message=message, link=link)
    if email_sender is None:
        return []
    wanted = [user for user in recipients if user.wants_email(category)]
    if wanted:
        email_sender(wanted)
    return wanted


def notify_users(users, *, category, title, message="", link=""):
    """여러 사용자에게 같은 알림을 한 번씩 만든다.

    호출하는 쪽에서 이미 같은 대상 목록을 넘긴다고 가정하고 중복 제거는 하지 않는다.
    """
    user_ids = {user.pk for user in users}
    Notification.objects.bulk_create(
        Notification(
            recipient_id=user_id,
            category=category,
            title=title,
            message=message,
            link=link,
        )
        for user_id in user_ids
    )


def unread_count(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def recent_notifications(user, limit=30):
    return Notification.objects.filter(recipient=user)[:limit]


def mark_read(*, user, notification_id):
    Notification.objects.filter(pk=notification_id, recipient=user, read_at__isnull=True).update(
        read_at=timezone.now()
    )


def mark_all_read(user):
    Notification.objects.filter(recipient=user, read_at__isnull=True).update(read_at=timezone.now())


def delete_notification(*, user, notification_id):
    Notification.objects.filter(pk=notification_id, recipient=user).delete()


def delete_all_notifications(user):
    Notification.objects.filter(recipient=user).delete()

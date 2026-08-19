from django.utils import timezone

from notifications.models import Notification


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

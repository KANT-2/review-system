from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from notifications.services import mark_all_read, mark_read, recent_notifications, unread_count


def _serialize(notification):
    return {
        "id": notification.pk,
        "category": notification.category,
        "title": notification.title,
        "message": notification.message,
        "link": notification.link,
        "created_at": notification.created_at.isoformat(),
        "is_read": notification.read_at is not None,
    }


@login_required
def summary(request):
    """종 아이콘이 주기적으로 조회하는 요약 - 배지 숫자와 최근 알림 목록을 함께 준다."""
    items = list(recent_notifications(request.user))
    return JsonResponse(
        {
            "unread_count": unread_count(request.user),
            "items": [_serialize(item) for item in items],
        }
    )


@login_required
@require_POST
def mark_read_view(request, notification_id):
    mark_read(user=request.user, notification_id=notification_id)
    return JsonResponse({"unread_count": unread_count(request.user)})


@login_required
@require_POST
def mark_all_read_view(request):
    mark_all_read(request.user)
    return JsonResponse({"unread_count": 0})

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse

from accounts.models import User
from audit.services import record_event
from notices.models import Notice
from notifications.models import Notification
from notifications.services import notify_users


def notice_rows():
    """공지 포털 목록 - 최신순, 작성자 정보를 함께 가져온다."""
    return Notice.objects.select_related("created_by")


def active_notices():
    """대시보드 공지 바에 노출할 공개 공지 - 최신순."""
    return Notice.objects.filter(is_published=True)


def _notify_students_of_notice(notice):
    notify_users(
        User.objects.filter(role=User.Role.STUDENT, is_active=True),
        category=Notification.Category.NOTICE,
        title="새 공지가 등록되었습니다",
        message=notice.title,
        # NOTICE 알림은 페이지 이동이 아니라 모달로 바로 띄운다 - 프론트(notifications.js)가
        # 이 주소를 fetch해서 내용을 채운다. 나중에 이 공지가 비공개·삭제되면 404가 나고,
        # 그때는 알림을 눌러도 조용히 실패 토스트만 뜬다(_openItem 쪽 처리).
        link=reverse("notices:notice-detail-json", kwargs={"notice_id": notice.pk}),
    )


@transaction.atomic
def save_notice(*, form, actor):
    is_create = form.instance.pk is None
    # form.is_valid()가 이미 form.instance에 새 값을 반영해 뒀으므로, 공개 전환 여부를
    # 판단하려면 DB에 남아 있는 저장 전 상태를 따로 조회해야 한다.
    was_published = (
        False
        if is_create
        else Notice.objects.filter(pk=form.instance.pk)
        .values_list("is_published", flat=True)
        .first()
    )
    notice = form.save(commit=False)
    if is_create:
        notice.created_by = actor
    notice.full_clean()
    notice.save()
    record_event(
        action="NOTICE_CREATED" if is_create else "NOTICE_UPDATED",
        target=notice,
        actor=actor,
        summary={"title": notice.title, "is_published": notice.is_published},
    )
    if notice.is_published and not was_published:
        _notify_students_of_notice(notice)
    return notice


@transaction.atomic
def delete_notice(*, notice_id, actor):
    try:
        notice = Notice.objects.get(pk=notice_id)
    except Notice.DoesNotExist as error:
        raise ValidationError("이미 삭제된 공지입니다.") from error
    record_event(
        action="NOTICE_DELETED", target=notice, actor=actor, summary={"title": notice.title}
    )
    notice.delete()


@transaction.atomic
def toggle_notice_publish(*, notice_id, actor):
    try:
        notice = Notice.objects.select_for_update().get(pk=notice_id)
    except Notice.DoesNotExist as error:
        raise ValidationError("이미 삭제된 공지입니다.") from error
    notice.is_published = not notice.is_published
    notice.save(update_fields=("is_published", "updated_at"))
    record_event(
        action="NOTICE_PUBLISHED" if notice.is_published else "NOTICE_UNPUBLISHED",
        target=notice,
        actor=actor,
        summary={"title": notice.title},
    )
    if notice.is_published:
        _notify_students_of_notice(notice)
    return notice

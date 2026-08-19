from django.core.exceptions import ValidationError
from django.db import transaction

from audit.services import record_event
from notices.models import Notice


def notice_rows():
    """공지 포털 목록 - 최신순, 작성자 정보를 함께 가져온다."""
    return Notice.objects.select_related("created_by")


def active_notices():
    """대시보드 공지 바에 노출할 공개 공지 - 최신순."""
    return Notice.objects.filter(is_published=True)


@transaction.atomic
def save_notice(*, form, actor):
    is_create = form.instance.pk is None
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
    return notice

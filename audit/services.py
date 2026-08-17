from audit.models import AuditEvent


def record_event(
    *, action, target, actor=None, actor_id=None, round_obj=None, summary=None, succeeded=True
):
    """민감 원문을 받지 않는 최소 감사 이벤트 기록 함수."""
    actor_kwargs = {"actor": actor} if actor is not None else {"actor_id": actor_id}
    return AuditEvent.objects.create(
        round=round_obj,
        **actor_kwargs,
        action=action,
        target_type=target._meta.label,
        target_id=str(target.pk),
        result=(AuditEvent.Result.SUCCEEDED if succeeded else AuditEvent.Result.FAILED),
        summary=summary or {},
    )

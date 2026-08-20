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


# 화면에 사람이 읽을 수 있는 이름으로 보여줄 액션 라벨. 없는 액션은 원문을 그대로 쓴다.
ACTION_LABELS = {
    "ROUND_STARTED": "회차 시작",
    "ROUND_COMPLETED": "회차 마감",
    "ROUND_FORCE_COMPLETED": "회차 강제 마감",
    "ROUND_REVERTED_TO_DRAFT": "회차 되돌리기",
    "ROUND_REOPENED": "회차 다시 열기",
    "ROUND_DELETED": "회차 삭제",
    "TEAM_CONFIGURATION_SAVED": "팀 편성 저장",
    "CALCULATION_SUCCEEDED": "채점 완료",
    "CALCULATION_FAILED": "채점 실패",
    "PUBLICATION_CHANGED": "결과 공개 변경",
    "TUTOR_NOTE_ADDED": "튜터 메모 추가",
    "TUTOR_NOTE_DELETED": "튜터 메모 삭제",
    "TUTOR_NOTE_ALL_DELETED": "튜터 메모 전체 삭제",
    "QUESTION_TEMPLATE_CREATED": "문항 템플릿 생성",
    "QUESTION_TEMPLATE_UPDATED": "문항 템플릿 수정",
    "QUESTION_TEMPLATE_COPIED": "문항 템플릿 복제",
    "QUESTION_TEMPLATE_DELETED": "문항 템플릿 삭제",
    "QUESTION_TEMPLATE_ARCHIVED": "문항 템플릿 보관",
    "QUESTION_TEMPLATE_RESTORED": "문항 템플릿 복원",
    "WHITELIST_ADDED": "명단 추가",
    "WHITELIST_UPDATED": "명단 수정",
    "WHITELIST_REMOVED": "명단 삭제",
    "ACCOUNT_APPROVAL_REVERTED": "승인 대기로 되돌림",
    "ACCOUNT_ROLE_CHANGED": "역할 변경",
    "ACCOUNT_PASSWORD_ROTATION_REQUIRED": "비밀번호 재설정 요구",
    "ACCOUNT_PASSWORD_RESET": "비밀번호 재설정",
    "ACCOUNT_PROFILE_UPDATED": "계정 정보 수정",
    "SOCIAL_ACCOUNT_LINKED": "소셜 계정 최초 연결",
    "NOTICE_CREATED": "공지 등록",
    "NOTICE_UPDATED": "공지 수정",
    "NOTICE_DELETED": "공지 삭제",
    "NOTICE_PUBLISHED": "공지 공개",
    "NOTICE_UNPUBLISHED": "공지 비공개 전환",
}


def audit_event_rows(*, round_id=None, action=None, actor_id=None):
    """감사 로그 조회 - 최근 것부터, 필요하면 회차·동작·수행자로 좁힌다."""
    events = AuditEvent.objects.select_related("actor", "round")
    if round_id:
        events = events.filter(round_id=round_id)
    if action:
        events = events.filter(action=action)
    if actor_id:
        events = events.filter(actor_id=actor_id)
    return events


def recorded_actions():
    """실제로 기록된 액션 목록 - 필터 선택지로 쓴다."""
    return sorted(AuditEvent.objects.values_list("action", flat=True).distinct())

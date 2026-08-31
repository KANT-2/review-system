"""ideas 앱의 순수 비즈니스 로직 (AI Coach 관련).

PRD Context를 실제 DB 데이터로부터 조립하고, Gemini 호출(ai_coach.py)과
연결한다. 뷰는 이 함수들을 호출하기만 하고 HTTP 요청/응답 처리에만 집중한다.
"""

from datetime import timedelta

from django.utils import timezone

from .ai_coach import AICoachError, generate_coach_reply
from .models import AIChatHistory

__all__ = [
    "AICoachError",
    "append_chat_turn",
    "ask_ai_coach",
    "build_prd_context",
    "cleanup_expired_chat_histories",
    "generate_question_draft",
    "get_chat_history",
]

# Gemini에 다시 실어 보낼 최근 대화 턴 수 ("방금 한 말 까먹는 문제" 방지용).
# chat_data 저장 자체는 항상 전체를 보존하고, 이 값은 프롬프트에 포함할 범위만 제한한다.
RECENT_TURNS_FOR_PROMPT = 3

# 대화 기록 보관 기간 (Q-010: 30일, 저장할 때마다 만료일을 갱신한다).
CHAT_HISTORY_TTL_DAYS = 30


def build_prd_context(project, *, current_section_title=None):
    """PRDProject의 실제 저장된 데이터만으로 Gemini에 전달할 Context 텍스트를 만든다.

    존재하지 않는 필드(예: Business Rules, Success Metrics 같은 표준 PRD 항목)는
    지어내지 않고, 실제 모델에 있는 정보(제목/설명/유형/상태/마감일 + 섹션별 질문-답변)만 사용한다.
    """
    lines = [
        f"프로젝트명: {project.title}",
        f"한 줄 소개: {project.description or '(작성되지 않음)'}",
        f"유형: {project.get_project_type_display()}",
        f"상태: {project.status}",
        f"마감일: {project.deadline or '(설정되지 않음)'}",
        "",
        "## 섹션별 작성 내용",
    ]

    for section in project.sections.all():
        lines.append(f"\n### {section.title}")
        if section.guidance:
            lines.append(f"(가이드: {section.guidance})")
        for question in section.questions.all():
            status = "[보류 중]" if question.is_held else ""
            answer = question.answer.strip() or "(아직 작성되지 않음)"
            lines.append(f"- Q. {question.question} {status}")
            lines.append(f"  A. {answer}")

    if current_section_title:
        lines.append(f"\n## 사용자가 현재 작성 중인 섹션\n{current_section_title}")

    return "\n".join(lines)


def get_chat_history(project, *, section, user):
    """(project, section, user) 하나에 대한 저장된 대화 배열 전체를 그대로 반환한다.

    프론트는 이 결과를 자르거나 가공하지 않고 그대로 화면에 복원한다.
    """
    history = AIChatHistory.objects.filter(prd=project, section=section, user=user).first()
    return history.chat_data if history else []


def append_chat_turn(project, *, section, user, user_message, ai_reply):
    """이번 질문/답변 한 쌍을 저장된 대화 배열 끝에 추가하고 UPSERT 저장한다.

    메시지마다 새 행을 만들지 않고, (prd, section, user) 행 하나의 chat_data를 통째로 갱신한다.
    """
    history, _created = AIChatHistory.objects.get_or_create(
        prd=project, section=section, user=user, defaults={"chat_data": []}
    )
    history.chat_data = [
        *history.chat_data,
        {"role": "user", "text": user_message},
        {"role": "model", "text": ai_reply},
    ]
    history.expires_at = timezone.localdate() + timedelta(days=CHAT_HISTORY_TTL_DAYS)
    history.save(update_fields=["chat_data", "expires_at"])
    return history.chat_data


def _recent_turns_text(chat_data, *, n_turns=RECENT_TURNS_FOR_PROMPT):
    """저장된 대화 중 최근 n_turns개 교환(사용자+AI 쌍)만 프롬프트용 텍스트로 만든다."""
    recent = chat_data[-(n_turns * 2) :]
    if not recent:
        return ""
    lines = []
    for turn in recent:
        speaker = "사용자" if turn.get("role") == "user" else "AI"
        lines.append(f"{speaker}: {turn.get('text', '')}")
    return "\n".join(lines)


def ask_ai_coach(project, *, section, user, message):
    """사용자 메시지 + PRD Context + 최근 대화를 합쳐 Gemini에 보내고 답변을 반환한다.

    저장된 chat_data 전체가 아니라 최근 RECENT_TURNS_FOR_PROMPT개 교환만 프롬프트에
    포함한다 (저장은 전체, 재사용은 일부). 성공하면 이번 질문/답변을 chat_data에 추가로 저장한다.
    """
    context = build_prd_context(project, current_section_title=section.title if section else None)

    chat_data = get_chat_history(project, section=section, user=user)
    recent_text = _recent_turns_text(chat_data)
    history_block = f"\n\n## 최근 대화\n{recent_text}" if recent_text else ""

    prompt = f"다음은 현재 PRD Context입니다.\n\n{context}{history_block}\n\n---\n\n사용자 질문:\n{message}"
    reply = generate_coach_reply(prompt=prompt, feature_type="COACHING")

    append_chat_turn(project, section=section, user=user, user_message=message, ai_reply=reply.text)

    return reply


def cleanup_expired_chat_histories(limit=500):
    """expires_at이 지난 AI_Chat_Histories 행을 삭제한다 (Q-010: 30일 TTL)."""
    today = timezone.localdate()
    ids = list(
        AIChatHistory.objects.filter(expires_at__lt=today)
        .order_by("expires_at")
        .values_list("pk", flat=True)[:limit]
    )
    return AIChatHistory.objects.filter(pk__in=ids).delete()[0]


def generate_question_draft(project, *, section, question):
    """특정 질문 하나에 대한 답변 초안을 Gemini에게 요청한다.

    이 결과는 곧바로 PRD에 저장되지 않는다 — 화면에서 사용자가 직접 검토·수정한 뒤
    "PRD에 반영하기"를 눌러야 실제 저장(prd_save_answer)으로 이어진다. AI가 초안을
    만드는 것과 사용자가 승인해 실제 데이터를 저장하는 것을 분리한다는 원칙에 따른다.
    """
    context = build_prd_context(project, current_section_title=section.title)
    prompt = (
        "다음은 현재 PRD Context입니다.\n\n"
        f"{context}\n\n"
        "---\n\n"
        f"다음 질문에 대한 답변 초안을 작성해줘. 반드시 위 PRD Context와 일관되게, "
        "이미 확정된 다른 섹션 내용과 충돌하지 않게 작성해줘. "
        "이 답변은 어디까지나 초안이고 사용자가 검토 후 직접 수정하거나 승인해야 확정된다는 점을 감안해서, "
        "설명 없이 답변 초안 본문만 출력해줘.\n\n"
        f"섹션: {section.title}\n"
        f"질문: {question.question}"
    )
    return generate_coach_reply(prompt=prompt, feature_type="COACHING")

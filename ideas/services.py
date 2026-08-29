"""ideas 앱의 순수 비즈니스 로직 (AI Coach 관련).

PRD Context를 실제 DB 데이터로부터 조립하고, Gemini 호출(ai_coach.py)과
연결한다. 뷰는 이 함수들을 호출하기만 하고 HTTP 요청/응답 처리에만 집중한다.
"""

from .ai_coach import AICoachError, generate_coach_reply

__all__ = ["AICoachError", "ask_ai_coach", "build_prd_context", "generate_question_draft"]


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


def ask_ai_coach(project, *, message, current_section_title=None):
    """사용자 메시지 + PRD Context를 합쳐 Gemini에 보내고 답변 텍스트를 반환한다.

    System Instructions / PRD Context / User Message는 별도 함수(ai_coach.py의
    시스템 지시문 로드, build_prd_context, 이 함수의 인자)로 분리되어 있다가
    이 지점에서 하나의 프롬프트로 합쳐진다.
    """
    context = build_prd_context(project, current_section_title=current_section_title)
    prompt = (
        "다음은 현재 PRD Context입니다.\n\n"
        f"{context}\n\n"
        "---\n\n"
        f"사용자 질문:\n{message}"
    )
    return generate_coach_reply(prompt=prompt, feature_type="COACHING")


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

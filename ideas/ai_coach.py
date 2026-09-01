"""Gemini API 호출만 담당하는 얇은 클라이언트 래퍼.

PRD Context 구성이나 프롬프트 조립은 여기서 하지 않는다 (services.py 담당).
System Instructions는 팀 공통 ERD의 AI_Prompts 테이블에서 읽어온다 (feature_type=COACHING,
is_active=True인 최신 버전) — 다른 기능(AI 채팅 등)과 같은 프롬프트를 공유하기 위함이다.
"""

from dataclasses import dataclass

from django.conf import settings


class AICoachError(Exception):
    """Gemini 호출이 실패했거나 설정이 안 됐을 때 발생한다."""


@dataclass
class CoachReply:
    text: str
    total_tokens: int | None


# 코칭 대화는 [현재 상태]/[제안]/[생각해볼 질문] 등 구조화된 답변이라 다소 길어질 수 있고,
# 초안 생성은 PRD 답변란에 그대로 들어가는 본문 하나뿐이라 짧아야 한다.
MAX_OUTPUT_TOKENS = {
    "COACHING": 1536,
    "GENERATE": 640,
}


def is_configured():
    return bool(settings.GEMINI_API_KEY)


def load_system_instruction(feature_type="COACHING"):
    from .models import AIPrompt

    prompt = (
        AIPrompt.objects.filter(feature_type=feature_type, is_active=True)
        .order_by("-version")
        .first()
    )
    if prompt is None:
        raise AICoachError(f"활성화된 AI_Prompts 행이 없습니다 (feature_type={feature_type}).")
    return prompt.system_instruction


def generate_coach_reply(*, prompt, feature_type="COACHING"):
    """prompt(PRD Context + 사용자 질문이 합쳐진 텍스트)를 Gemini에 보내고 응답을 반환한다.

    API 키가 없거나 호출이 실패하면 AICoachError를 발생시킨다.
    """
    if not is_configured():
        raise AICoachError("GEMINI_API_KEY가 설정되어 있지 않습니다.")

    system_instruction = load_system_instruction(feature_type=feature_type)

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        max_output_tokens=MAX_OUTPUT_TOKENS.get(feature_type, MAX_OUTPUT_TOKENS["COACHING"]),
        http_options=types.HttpOptions(timeout=settings.GEMINI_TIMEOUT_MS),
    )

    # Gemini가 간헐적으로 느려지거나(타임아웃) 일시적으로 응답을 못 주는 경우가 있어,
    # 한 번 실패하면 바로 포기하지 않고 한 번 더 시도한다. 그래도 안 되면 진짜 실패로 처리한다.
    last_exc = None
    response = None
    for _attempt in range(2):
        try:
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL, contents=prompt, config=config
            )
            break
        except Exception as exc:  # Gemini SDK가 던지는 예외 유형이 다양해 광범위하게 잡는다
            last_exc = exc

    if response is None:
        raise AICoachError("Gemini API 호출에 실패했습니다.") from last_exc

    text = getattr(response, "text", None)
    if not text:
        raise AICoachError("Gemini로부터 빈 응답을 받았습니다.")

    usage = getattr(response, "usage_metadata", None)
    total_tokens = getattr(usage, "total_token_count", None) if usage else None

    return CoachReply(text=text, total_tokens=total_tokens)

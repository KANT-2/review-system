from pathlib import Path

from django.core.management.base import BaseCommand

from ideas.models import AIPrompt

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# feature_type별로 별도의 system_instruction 파일을 둔다 — 코칭 대화(구조화된 답변)와
# 초안 생성(답변 본문만) 은 요구되는 출력 형태가 달라 프롬프트를 공유하지 않는다.
PROMPT_FILES = {
    AIPrompt.FeatureType.COACHING: PROMPTS_DIR / "ai_coach_system.txt",
    AIPrompt.FeatureType.GENERATE: PROMPTS_DIR / "ai_coach_generate.txt",
}


class Command(BaseCommand):
    help = "AI_Prompts 테이블에 PRD Studio AI Coach의 초기 system_instruction을 등록한다."

    def handle(self, *args, **options):
        for feature_type, path in PROMPT_FILES.items():
            text = path.read_text(encoding="utf-8")
            prompt, created = AIPrompt.objects.update_or_create(
                feature_type=feature_type,
                version="v1.0",
                defaults={"system_instruction": text, "is_active": True},
            )
            verb = "생성" if created else "갱신"
            self.stdout.write(self.style.SUCCESS(f"AI_Prompts {verb}됨: {prompt}"))

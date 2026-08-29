from pathlib import Path

from django.core.management.base import BaseCommand

from ideas.models import AIPrompt

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "ai_coach_system.txt"


class Command(BaseCommand):
    help = "AI_Prompts 테이블에 PRD Studio AI Coach의 초기 system_instruction을 등록한다."

    def handle(self, *args, **options):
        text = PROMPT_PATH.read_text(encoding="utf-8")

        prompt, created = AIPrompt.objects.update_or_create(
            feature_type=AIPrompt.FeatureType.COACHING,
            version="v1.0",
            defaults={"system_instruction": text, "is_active": True},
        )
        verb = "생성" if created else "갱신"
        self.stdout.write(self.style.SUCCESS(f"AI_Prompts {verb}됨: {prompt}"))

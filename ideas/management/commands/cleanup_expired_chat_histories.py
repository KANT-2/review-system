from django.core.management.base import BaseCommand

from ideas.services import cleanup_expired_chat_histories


class Command(BaseCommand):
    help = "만료된 AI_Chat_Histories 행을 정리합니다 (Q-010: 30일 TTL)."

    def handle(self, *args, **options):
        rows = cleanup_expired_chat_histories()
        self.stdout.write(self.style.SUCCESS(f"chat_history_rows={rows}"))

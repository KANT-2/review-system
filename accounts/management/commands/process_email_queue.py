from django.core.management.base import BaseCommand

from accounts.scheduler_services import (
    process_auto_submission_reminders,
    process_scheduled_emails,
)


class Command(BaseCommand):
    help = "예약 공지 메일과 평가 마감 10분 전 자동 제출 안내 메일을 발송합니다."

    def handle(self, *args, **options):
        scheduled_count = process_scheduled_emails()
        auto_reminder_count = process_auto_submission_reminders()

        self.stdout.write(
            self.style.SUCCESS(
                f"스케줄러 실행 완료: 예약 메일 처리 {scheduled_count}건, 마감 10분 전 제출 안내 처리 회차 {auto_reminder_count}건"
            )
        )

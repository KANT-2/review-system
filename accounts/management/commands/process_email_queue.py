from django.core.management.base import BaseCommand

from accounts.scheduler_services import (
    process_auto_submission_reminders,
    process_scheduled_emails,
)


class Command(BaseCommand):
    help = "예약 이메일 공지 전송 및 평가 마감 10분 전 자동 독촉 이메일 발송 작업을 실행합니다."

    def handle(self, *args, **options):
        scheduled_count = process_scheduled_emails()
        auto_reminder_count = process_auto_submission_reminders()

        self.stdout.write(
            self.style.SUCCESS(
                f"스케줄러 실행 완료: 예약 메일 처리 {scheduled_count}건, 마감 10분 전 자동 독촉 처리 회차 {auto_reminder_count}건"
            )
        )

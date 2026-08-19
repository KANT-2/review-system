from django.core import mail
from django.test import TestCase

from accounts.email_services import (
    send_results_released_email,
    send_round_started_email,
    send_submission_reminder_email,
    send_tutor_announcement_email,
)
from rounds.models import EvaluationRound


class EmailNotificationServicesTestCase(TestCase):
    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from accounts.models import User

        self.user = User.objects.create_user(email="creator@example.com", password="password")
        self.round_obj = EvaluationRound.objects.create(
            title="1차 미니프로젝트 발표회",
            status=EvaluationRound.Status.DRAFT,
            evaluation_start_at=timezone.now(),
            evaluation_end_at=timezone.now() + timedelta(days=7),
            created_by=self.user,
        )

    def test_send_tutor_announcement_email(self):
        recipients = ["studentA@example.com", "studentB@example.com"]
        sent_count = send_tutor_announcement_email(
            "팀 긴급 공지", "1조 발표 일정 변경 안내", recipients
        )

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("[AX 평가 공지]", mail.outbox[0].subject)

    def test_send_round_started_email(self):
        recipients = ["student1@example.com"]
        sent_count = send_round_started_email(self.round_obj, recipients)

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("1차 미니프로젝트 발표회", mail.outbox[0].subject)
        self.assertIn("평가가 개시되었습니다", mail.outbox[0].subject)

    def test_send_results_released_email(self):
        recipients = ["student1@example.com"]
        sent_count = send_results_released_email(self.round_obj, recipients)

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("최종 성적 및 피드백이 공개되었습니다", mail.outbox[0].subject)

    def test_send_submission_reminder_email(self):
        sent_count = send_submission_reminder_email(self.round_obj, "홍길동", "hong@example.com")

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("평가 제출 안내", mail.outbox[0].subject)

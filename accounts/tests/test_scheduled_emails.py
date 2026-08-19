from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from accounts.models import ScheduledEmail, User
from accounts.scheduler_services import (
    process_auto_submission_reminders,
    process_scheduled_emails,
)
from rounds.models import EvaluationRound, RoundParticipant
from teams.models import Team, TeamMembership


class ScheduledEmailsTestCase(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="tutor_test@example.com",
            password="password",
            role=User.Role.ADMIN,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=True,
        )
        self.student = User.objects.create_user(
            email="student_test@example.com",
            password="password",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def test_process_scheduled_emails(self):
        # 도래한 예약 메일 생성 (1분 전으로 설정)
        scheduled_item = ScheduledEmail.objects.create(
            sender=self.tutor,
            subject="예약된 공지 메일",
            message="1분 전에 예약된 테스트 메일입니다.",
            target_type=ScheduledEmail.TargetType.ALL,
            scheduled_at=timezone.now() - timedelta(minutes=1),
            status=ScheduledEmail.Status.PENDING,
        )

        processed_count = process_scheduled_emails()

        scheduled_item.refresh_from_db()
        self.assertEqual(processed_count, 1)
        self.assertEqual(scheduled_item.status, ScheduledEmail.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("예약된 공지 메일", mail.outbox[0].subject)

    def test_process_auto_submission_reminders_10_min_before_end(self):
        # 마감 시각이 5분 뒤로 남은 진행 중인 평가 회차 생성
        round_obj = EvaluationRound.objects.create(
            title="마감 임박 회차",
            status=EvaluationRound.Status.IN_PROGRESS,
            evaluation_start_at=timezone.now() - timedelta(hours=1),
            evaluation_end_at=timezone.now() + timedelta(minutes=5),
            created_by=self.tutor,
        )
        participant = RoundParticipant.objects.create(
            round=round_obj,
            user=self.student,
            student_number_snapshot="EMAIL001",
            display_name_snapshot="이메일 테스트 학생",
        )
        assigned_team = Team.objects.create(round=round_obj, team_number=1, name="1팀")
        Team.objects.create(round=round_obj, team_number=2, name="2팀")
        TeamMembership.objects.create(team=assigned_team, participant=participant)

        reminded_rounds_count = process_auto_submission_reminders()

        round_obj.refresh_from_db()
        self.assertEqual(reminded_rounds_count, 1)
        self.assertIsNotNone(round_obj.auto_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("평가 제출 안내", mail.outbox[0].subject)

        # 2번째 실행 시 제출 안내 메일이 중복 발송되지 않는지 검증
        mail.outbox.clear()
        second_run_count = process_auto_submission_reminders()
        self.assertEqual(second_run_count, 0)
        self.assertEqual(len(mail.outbox), 0)

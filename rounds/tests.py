from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from rounds.models import EvaluationRound, QuestionTemplate, RoundParticipant, TemplateQuestion
from rounds.services import start_round
from teams.models import Team, TeamMembership


class RoundLifecycleTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="round-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.students = [
            User.objects.create_user(
                email=f"round-student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"R{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
            )
            for index in range(1, 5)
        ]
        self.team_template = QuestionTemplate.objects.create(
            name="팀 평가", category="TEAM", created_by=self.tutor
        )
        self.peer_template = QuestionTemplate.objects.create(
            name="개인 평가", category="PEER", created_by=self.tutor
        )
        TemplateQuestion.objects.create(
            template=self.team_template,
            response_type="RATING_5",
            prompt="팀 점수",
            display_order=1,
        )
        TemplateQuestion.objects.create(
            template=self.peer_template,
            response_type="RATING_5",
            prompt="개인 점수",
            display_order=1,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="동결 테스트",
            evaluation_start_at=now,
            evaluation_end_at=now + timedelta(days=1),
            target_team_count=2,
            team_template=self.team_template,
            peer_template=self.peer_template,
            created_by=self.tutor,
        )
        participants = [
            RoundParticipant.objects.create(
                round=self.round,
                user=user,
                student_number_snapshot=user.student_number,
                display_name_snapshot=user.first_name,
            )
            for user in self.students
        ]
        teams = [
            Team.objects.create(round=self.round, team_number=index, name=f"{index}팀")
            for index in (1, 2)
        ]
        for index, participant in enumerate(participants):
            TeamMembership.objects.create(team=teams[index % 2], participant=participant)

    def test_round_starts_only_when_complete_and_records_audit(self):
        result = start_round(round_id=self.round.pk, actor=self.tutor)
        self.assertEqual(result.status, EvaluationRound.Status.IN_PROGRESS)
        self.assertTrue(AuditEvent.objects.filter(action="ROUND_STARTED").exists())
        with self.assertRaises(ValidationError):
            self.team_template.name = "변경 금지"
            self.team_template.save()

    def test_second_in_progress_round_is_rejected(self):
        start_round(round_id=self.round.pk, actor=self.tutor)
        other = EvaluationRound.objects.create(
            title="두 번째",
            evaluation_start_at=timezone.now(),
            evaluation_end_at=timezone.now() + timedelta(days=1),
            target_team_count=2,
            team_template=self.team_template,
            peer_template=self.peer_template,
            created_by=self.tutor,
        )
        other_participants = [
            RoundParticipant.objects.create(
                round=other,
                user=user,
                student_number_snapshot=user.student_number,
                display_name_snapshot=user.first_name,
            )
            for user in self.students
        ]
        other_teams = [
            Team.objects.create(round=other, team_number=index, name=f"{index}팀")
            for index in (1, 2)
        ]
        for index, participant in enumerate(other_participants):
            TeamMembership.objects.create(team=other_teams[index % 2], participant=participant)
        with self.assertRaises(ValidationError):
            start_round(round_id=other.pk, actor=self.tutor)

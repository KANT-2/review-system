from datetime import timedelta
from random import Random

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from rounds.models import EvaluationRound, RoundParticipant
from teams.contracts import AutoAssignmentRequest, TeamSaveRequest
from teams.django_backend import build_django_teams_backend


class DjangoTeamsBackendTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="team-backend-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="팀 저장 회차",
            evaluation_start_at=now,
            evaluation_end_at=now + timedelta(days=1),
            target_team_count=2,
            created_by=self.tutor,
        )
        self.participants = []
        for index in range(1, 7):
            user = User.objects.create_user(
                email=f"team-backend-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"T{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
            )
            self.participants.append(
                RoundParticipant.objects.create(
                    round=self.round,
                    user=user,
                    student_number_snapshot=user.student_number,
                    display_name_snapshot=user.first_name,
                )
            )

    def test_auto_board_can_be_saved_and_queried(self):
        backend = build_django_teams_backend()
        backend.rng_factory = lambda: Random(7)
        proposal = backend.create_auto_assignment(
            self.round.pk,
            AutoAssignmentRequest(team_count=2, lock_version=0),
        )
        saved = backend.save_team_configuration(
            self.round.pk,
            self.tutor.pk,
            TeamSaveRequest(board=proposal.board, imbalance_confirmed=False),
        )
        self.assertEqual(saved.lock_version, 1)
        view = backend.get_management_team(self.round.pk)
        self.assertEqual(len(view.teams), 2)
        self.assertEqual(sum(len(team.members) for team in view.teams), 6)
        self.assertTrue(AuditEvent.objects.filter(action="TEAM_CONFIGURATION_SAVED").exists())

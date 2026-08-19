import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.services import unread_count
from rounds.models import EvaluationRound, RoundParticipant


class SaveTeamViewNotificationTests(TestCase):
    """실제 HTTP 저장 흐름(teams:save-team)이 팀 배정 알림까지 만드는지 확인한다.

    save_team_configuration 자체(teams/application.py)는 프레임워크와 무관한 순수
    로직이라 거기서는 알림을 만들지 않는다 - 뷰(teams/views.py)가 저장 성공 후에 만든다.
    """

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="team-notify-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="팀 알림 회차",
            evaluation_start_at=now,
            evaluation_end_at=now + timedelta(days=1),
            target_team_count=2,
            created_by=self.tutor,
        )
        self.participants = []
        for index in range(1, 5):
            user = User.objects.create_user(
                email=f"team-notify-student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"TN{index:03d}",
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

    def test_saving_teams_notifies_each_teams_members(self):
        self.client.force_login(self.tutor)
        payload = {
            "lock_version": 0,
            "teams": [
                {
                    "team_number": 1,
                    "name": "1팀",
                    "participant_ids": [self.participants[0].pk, self.participants[1].pk],
                },
                {
                    "team_number": 2,
                    "name": "2팀",
                    "participant_ids": [self.participants[2].pk, self.participants[3].pk],
                },
            ],
        }

        response = self.client.post(
            reverse("teams:save-team", kwargs={"round_id": self.round.pk}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        for participant in self.participants:
            self.assertEqual(unread_count(participant.user), 1)

    def test_saving_teams_again_sends_another_round_of_notifications(self):
        """편성을 다시 저장하면 그때마다 알림이 또 간다 - 저장 자체가 배정 확정을 뜻한다."""
        self.client.force_login(self.tutor)
        first_payload = {
            "lock_version": 0,
            "teams": [
                {
                    "team_number": 1,
                    "name": "1팀",
                    "participant_ids": [self.participants[0].pk, self.participants[1].pk],
                },
                {
                    "team_number": 2,
                    "name": "2팀",
                    "participant_ids": [self.participants[2].pk, self.participants[3].pk],
                },
            ],
        }
        self.client.post(
            reverse("teams:save-team", kwargs={"round_id": self.round.pk}),
            data=json.dumps(first_payload),
            content_type="application/json",
        )
        second_payload = {**first_payload, "lock_version": 1}

        self.client.post(
            reverse("teams:save-team", kwargs={"round_id": self.round.pk}),
            data=json.dumps(second_payload),
            content_type="application/json",
        )

        self.assertEqual(unread_count(self.participants[0].user), 2)

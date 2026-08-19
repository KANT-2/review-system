from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.services import ACTION_LABELS, record_event
from rounds.models import EvaluationRound


class AuditLogScreenTests(TestCase):
    """감사 로그 조회 - 누가 언제 무엇을 했는지 운영자가 화면에서 확인해야 한다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="audit-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.student = User.objects.create_user(
            email="audit-student@example.com",
            password="strong-test-password",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="감사 회차",
            evaluation_start_at=now,
            evaluation_end_at=now + timedelta(days=1),
            target_team_count=2,
            created_by=self.tutor,
        )
        self.other_round = EvaluationRound.objects.create(
            title="다른 회차",
            evaluation_start_at=now,
            evaluation_end_at=now + timedelta(days=1),
            target_team_count=2,
            created_by=self.tutor,
        )
        record_event(
            action="ROUND_STARTED",
            target=self.round,
            actor=self.tutor,
            round_obj=self.round,
            summary={"participant_count": 4},
        )
        record_event(
            action="PUBLICATION_CHANGED",
            target=self.other_round,
            actor=self.tutor,
            round_obj=self.other_round,
            summary={"item": "team_winner", "published": True},
        )
        self.client.force_login(self.tutor)

    def test_log_lists_events_with_readable_labels(self):
        response = self.client.get(reverse("audit:log"))

        self.assertEqual(response.context["page"].paginator.count, 2)
        self.assertContains(response, "회차 시작")
        self.assertContains(response, "결과 공개 변경")
        self.assertContains(response, "participant_count=4")

    def test_log_filters_by_round(self):
        response = self.client.get(reverse("audit:log"), {"round": self.round.pk})

        actions = [event.action for event in response.context["page"]]
        self.assertEqual(actions, ["ROUND_STARTED"])

    def test_log_filters_by_action_and_actor(self):
        by_action = self.client.get(reverse("audit:log"), {"action": "PUBLICATION_CHANGED"})
        by_actor = self.client.get(reverse("audit:log"), {"actor": self.tutor.pk})
        by_other_actor = self.client.get(reverse("audit:log"), {"actor": self.student.pk})

        self.assertEqual(by_action.context["page"].paginator.count, 1)
        self.assertEqual(by_actor.context["page"].paginator.count, 2)
        self.assertEqual(by_other_actor.context["page"].paginator.count, 0)

    def test_bad_filter_values_are_ignored(self):
        response = self.client.get(reverse("audit:log"), {"round": "<script>", "actor": "abc"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page"].paginator.count, 2)

    def test_students_cannot_read_the_audit_log(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("audit:log"))

        self.assertEqual(response.status_code, 403)


class AuditActionLabelTests(TestCase):
    """화면은 라벨이 없으면 액션 원문(CALCULATION_SUCCEEDED)을 그대로 보여준다.

    실제로 기록하는 액션은 아래 목록뿐이므로, 새 액션을 추가하면 라벨도 같이 추가해야 한다.
    (`grep -rn 'action="' --include='*.py'`로 확인한 목록)
    """

    RECORDED_ACTIONS = [
        "ACCOUNT_APPROVAL_REVERTED",
        "ACCOUNT_PASSWORD_RESET",
        "ACCOUNT_PASSWORD_ROTATION_REQUIRED",
        "ACCOUNT_PROFILE_UPDATED",
        "ACCOUNT_ROLE_CHANGED",
        "CALCULATION_FAILED",
        "CALCULATION_SUCCEEDED",
        "PUBLICATION_CHANGED",
        "QUESTION_TEMPLATE_COPIED",
        "QUESTION_TEMPLATE_CREATED",
        "QUESTION_TEMPLATE_DELETED",
        "QUESTION_TEMPLATE_UPDATED",
        "ROUND_COMPLETED",
        "ROUND_DELETED",
        "ROUND_FORCE_COMPLETED",
        "ROUND_REOPENED",
        "ROUND_REVERTED_TO_DRAFT",
        "ROUND_STARTED",
        "SOCIAL_ACCOUNT_LINKED",
        "TEAM_CONFIGURATION_SAVED",
        "TUTOR_NOTE_ADDED",
        "TUTOR_NOTE_DELETED",
        "TUTOR_NOTE_ALL_DELETED",
        "WHITELIST_ADDED",
        "WHITELIST_REMOVED",
        "WHITELIST_UPDATED",
    ]

    def test_every_recorded_action_has_a_korean_label(self):
        missing = [action for action in self.RECORDED_ACTIONS if action not in ACTION_LABELS]

        self.assertEqual(missing, [])

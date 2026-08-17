from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
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


class QuestionTemplateScreenTests(TestCase):
    """운영자가 Django admin 없이 문항 템플릿을 관리할 수 있어야 한다.

    회차 시작 조건에 팀·개인 템플릿이 필수라(rounds.services.round_start_errors) 이 화면이
    없으면 튜터 혼자서는 회차를 굴릴 수 없다.
    """

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="template-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.student = User.objects.create_user(
            email="template-student@example.com",
            password="strong-test-password",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True,
        )
        self.client.force_login(self.tutor)

    def _payload(self, **overrides):
        payload = {
            "name": "5기 팀 평가",
            "description": "기본 팀 평가",
            "category": "TEAM",
            "questions-TOTAL_FORMS": "3",
            "questions-INITIAL_FORMS": "0",
            "questions-MIN_NUM_FORMS": "1",
            "questions-MAX_NUM_FORMS": "1000",
            "questions-0-prompt": "결과물의 완성도는 충분한가요?",
            "questions-0-response_type": "RATING_5",
            "questions-0-is_required": "on",
            "questions-1-prompt": "발표가 명확했나요?",
            "questions-1-response_type": "RATING_5",
            "questions-2-prompt": "",
            "questions-2-response_type": "TEXT",
        }
        payload.update(overrides)
        return payload

    def test_tutor_creates_template_with_ordered_questions(self):
        response = self.client.post(reverse("rounds:template-create"), self._payload())

        self.assertRedirects(response, reverse("rounds:template-list"))
        template = QuestionTemplate.objects.get(name="5기 팀 평가")
        self.assertEqual(template.created_by, self.tutor)
        prompts = list(
            template.questions.order_by("display_order").values_list("prompt", flat=True)
        )
        self.assertEqual(prompts, ["결과물의 완성도는 충분한가요?", "발표가 명확했나요?"])
        self.assertEqual(
            list(
                template.questions.order_by("display_order").values_list("display_order", flat=True)
            ),
            [1, 2],
        )
        self.assertTrue(AuditEvent.objects.filter(action="QUESTION_TEMPLATE_CREATED").exists())

    def test_blank_question_rows_are_ignored(self):
        self.client.post(reverse("rounds:template-create"), self._payload())

        self.assertEqual(QuestionTemplate.objects.get(name="5기 팀 평가").questions.count(), 2)

    def test_template_needs_at_least_one_question(self):
        response = self.client.post(
            reverse("rounds:template-create"),
            self._payload(**{"questions-0-prompt": "", "questions-1-prompt": ""}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(QuestionTemplate.objects.filter(name="5기 팀 평가").exists())

    def test_template_used_by_started_round_is_read_only(self):
        template = QuestionTemplate.objects.create(
            name="사용 중 템플릿", category="TEAM", created_by=self.tutor
        )
        TemplateQuestion.objects.create(
            template=template, response_type="RATING_5", prompt="문항", display_order=1
        )
        now = timezone.now()
        EvaluationRound.objects.create(
            title="진행 중 회차",
            status=EvaluationRound.Status.IN_PROGRESS,
            evaluation_start_at=now,
            evaluation_end_at=now + timedelta(days=1),
            target_team_count=2,
            team_template=template,
            created_by=self.tutor,
            started_at=now,
        )

        page = self.client.get(reverse("rounds:template-edit", args=[template.pk]))
        self.assertContains(page, "읽기 전용")

        edit = self.client.post(
            reverse("rounds:template-edit", args=[template.pk]),
            self._payload(name="바꿔치기", questions_INITIAL="1"),
        )
        delete = self.client.post(reverse("rounds:template-delete", args=[template.pk]))

        self.assertRedirects(edit, reverse("rounds:template-list"))
        self.assertRedirects(delete, reverse("rounds:template-list"))
        template.refresh_from_db()
        self.assertEqual(template.name, "사용 중 템플릿")
        self.assertTrue(QuestionTemplate.objects.filter(pk=template.pk).exists())

    def test_copy_duplicates_questions_and_opens_the_copy(self):
        template = QuestionTemplate.objects.create(
            name="원본", category="PEER", created_by=self.tutor
        )
        TemplateQuestion.objects.create(
            template=template, response_type="RATING_5", prompt="기여도", display_order=1
        )

        response = self.client.post(reverse("rounds:template-copy", args=[template.pk]))

        copy = QuestionTemplate.objects.get(name="원본 (사본)")
        self.assertRedirects(response, reverse("rounds:template-edit", args=[copy.pk]))
        self.assertEqual(copy.copied_from, template)
        self.assertEqual(copy.category, template.category)
        self.assertEqual(list(copy.questions.values_list("prompt", flat=True)), ["기여도"])

    def test_unused_template_can_be_deleted(self):
        template = QuestionTemplate.objects.create(
            name="지울 템플릿", category="TEAM", created_by=self.tutor
        )

        self.client.post(reverse("rounds:template-delete", args=[template.pk]))

        self.assertFalse(QuestionTemplate.objects.filter(pk=template.pk).exists())

    def test_students_cannot_reach_template_screens(self):
        self.client.force_login(self.student)

        for response in (
            self.client.get(reverse("rounds:template-list")),
            self.client.get(reverse("rounds:template-create")),
        ):
            self.assertEqual(response.status_code, 403)

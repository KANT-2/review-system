from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from results.models import CalculationRun
from reviews.models import ReviewAnswer, ReviewSubmission, TutorReview
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


class RoundLifecycleReversalTests(TestCase):
    """운영 실수를 되돌리는 경로 - 삭제·준비 중으로 되돌리기·다시 열기."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="lifecycle-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.student = User.objects.create_user(
            email="lifecycle-student@example.com",
            password="strong-test-password",
            student_number="L001",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True,
        )
        self.client.force_login(self.tutor)

    def _round(self, status=EvaluationRound.Status.DRAFT, **extra):
        now = timezone.now()
        round_obj = EvaluationRound.objects.create(
            title="되돌리기 회차",
            status=status,
            evaluation_start_at=now,
            evaluation_end_at=now + timedelta(days=1),
            target_team_count=2,
            created_by=self.tutor,
            started_at=now if status != EvaluationRound.Status.DRAFT else None,
            completed_at=now if status == EvaluationRound.Status.COMPLETED else None,
            **extra,
        )
        participant = RoundParticipant.objects.create(
            round=round_obj,
            user=self.student,
            student_number_snapshot="L001",
            display_name_snapshot="학생",
        )
        team = Team.objects.create(round=round_obj, team_number=1, name="1팀")
        TeamMembership.objects.create(team=team, participant=participant)
        return round_obj

    def test_draft_round_is_deleted_with_teams_and_participants(self):
        round_obj = self._round()

        response = self.client.post(reverse("rounds:delete", args=[round_obj.pk]))

        self.assertRedirects(response, reverse("rounds:list"))
        self.assertFalse(EvaluationRound.objects.filter(pk=round_obj.pk).exists())
        self.assertFalse(Team.objects.filter(round_id=round_obj.pk).exists())
        self.assertFalse(RoundParticipant.objects.filter(round_id=round_obj.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(action="ROUND_DELETED").exists())

    def test_started_round_cannot_be_deleted(self):
        round_obj = self._round(status=EvaluationRound.Status.IN_PROGRESS)

        self.client.post(reverse("rounds:delete", args=[round_obj.pk]))

        self.assertTrue(EvaluationRound.objects.filter(pk=round_obj.pk).exists())

    def test_started_round_reverts_to_draft_when_nothing_submitted(self):
        round_obj = self._round(status=EvaluationRound.Status.IN_PROGRESS)

        self.client.post(reverse("rounds:revert", args=[round_obj.pk]))

        round_obj.refresh_from_db()
        self.assertEqual(round_obj.status, EvaluationRound.Status.DRAFT)
        self.assertIsNone(round_obj.started_at)
        self.assertTrue(AuditEvent.objects.filter(action="ROUND_REVERTED_TO_DRAFT").exists())

    def test_round_with_submissions_is_not_reverted(self):
        template = QuestionTemplate.objects.create(
            name="되돌리기 팀", category="TEAM", created_by=self.tutor
        )
        question = TemplateQuestion.objects.create(
            template=template, response_type="RATING_5", prompt="문항", display_order=1
        )
        round_obj = self._round(status=EvaluationRound.Status.IN_PROGRESS, team_template=template)
        other_team = Team.objects.create(round=round_obj, team_number=2, name="2팀")
        submission = ReviewSubmission.objects.create(
            round=round_obj,
            review_type="TEAM",
            evaluator=round_obj.participants.first(),
            target_team=other_team,
        )
        ReviewAnswer.objects.create(submission=submission, question=question, rating_value=4)

        self.client.post(reverse("rounds:revert", args=[round_obj.pk]))

        round_obj.refresh_from_db()
        self.assertEqual(round_obj.status, EvaluationRound.Status.IN_PROGRESS)

    def test_completed_round_reopens_when_not_scored(self):
        round_obj = self._round(status=EvaluationRound.Status.COMPLETED)

        self.client.post(reverse("rounds:reopen", args=[round_obj.pk]))

        round_obj.refresh_from_db()
        self.assertEqual(round_obj.status, EvaluationRound.Status.IN_PROGRESS)
        self.assertIsNone(round_obj.completed_at)
        self.assertTrue(AuditEvent.objects.filter(action="ROUND_REOPENED").exists())

    def test_scored_round_is_not_reopened(self):
        round_obj = self._round(status=EvaluationRound.Status.COMPLETED)
        CalculationRun.objects.create(
            round=round_obj,
            version=1,
            formula_version="score-v1",
            executed_by=self.tutor,
            status=CalculationRun.Status.SUCCEEDED,
            is_active=True,
            finished_at=timezone.now(),
        )

        self.client.post(reverse("rounds:reopen", args=[round_obj.pk]))

        round_obj.refresh_from_db()
        self.assertEqual(round_obj.status, EvaluationRound.Status.COMPLETED)

    def test_reopen_is_blocked_while_another_round_is_running(self):
        self._round(status=EvaluationRound.Status.IN_PROGRESS)
        completed = self._round(status=EvaluationRound.Status.COMPLETED)

        self.client.post(reverse("rounds:reopen", args=[completed.pk]))

        completed.refresh_from_db()
        self.assertEqual(completed.status, EvaluationRound.Status.COMPLETED)

    def test_students_cannot_reverse_rounds(self):
        round_obj = self._round()
        self.client.force_login(self.student)

        response = self.client.post(reverse("rounds:delete", args=[round_obj.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(EvaluationRound.objects.filter(pk=round_obj.pk).exists())


class TextAnswerScreenTests(TestCase):
    """서술형 응답 열람 - 운영자만, 원문 그대로(RES-013)."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="text-tutor@example.com",
            password="strong-test-password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.students = [
            User.objects.create_user(
                email=f"text-student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"T{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
                is_onboarded=True,
            )
            for index in range(1, 5)
        ]
        team_template = QuestionTemplate.objects.create(
            name="팀", category=QuestionTemplate.Category.TEAM, created_by=self.tutor
        )
        self.rating_question = TemplateQuestion.objects.create(
            template=team_template,
            response_type=TemplateQuestion.ResponseType.RATING_5,
            prompt="완성도는?",
            display_order=1,
        )
        self.text_question = TemplateQuestion.objects.create(
            template=team_template,
            response_type=TemplateQuestion.ResponseType.TEXT,
            prompt="인상 깊었던 점은?",
            display_order=2,
        )
        peer_template = QuestionTemplate.objects.create(
            name="개인", category=QuestionTemplate.Category.PEER, created_by=self.tutor
        )
        TemplateQuestion.objects.create(
            template=peer_template,
            response_type=TemplateQuestion.ResponseType.RATING_5,
            prompt="기여도는?",
            display_order=1,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="서술형 회차",
            status=EvaluationRound.Status.IN_PROGRESS,
            evaluation_start_at=now - timedelta(hours=1),
            evaluation_end_at=now + timedelta(hours=1),
            target_team_count=2,
            team_template=team_template,
            peer_template=peer_template,
            created_by=self.tutor,
            started_at=now,
        )
        self.participants = [
            RoundParticipant.objects.create(
                round=self.round,
                user=user,
                student_number_snapshot=user.student_number,
                display_name_snapshot=user.first_name,
            )
            for user in self.students
        ]
        team_one = Team.objects.create(round=self.round, team_number=1, name="1팀")
        self.team_two = Team.objects.create(round=self.round, team_number=2, name="2팀")
        for participant in self.participants[:2]:
            TeamMembership.objects.create(team=team_one, participant=participant)
        for participant in self.participants[2:]:
            TeamMembership.objects.create(team=self.team_two, participant=participant)
        submission = ReviewSubmission.objects.create(
            round=self.round,
            evaluator=self.participants[0],
            review_type=ReviewSubmission.ReviewType.TEAM,
            target_team=self.team_two,
        )
        ReviewAnswer.objects.create(
            submission=submission, question=self.rating_question, rating_value=4
        )
        ReviewAnswer.objects.create(
            submission=submission,
            question=self.text_question,
            text_value="발표 흐름이 매끄러웠습니다.",
        )
        self.url = reverse("rounds:text-answers", args=(self.round.pk,))

    def test_tutor_reads_the_free_text_answers(self):
        self.client.force_login(self.tutor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "인상 깊었던 점은?")
        self.assertContains(response, "발표 흐름이 매끄러웠습니다.")
        self.assertContains(response, "학생1")
        self.assertContains(response, "2팀")

    def test_rating_answers_are_not_listed_here(self):
        self.client.force_login(self.tutor)

        response = self.client.get(self.url)

        self.assertNotContains(response, "완성도는?")

    def test_students_cannot_open_it(self):
        self.client.force_login(self.students[0])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_blank_text_answers_cannot_even_be_stored(self):
        """빈 응답은 화면에서 거를 필요도 없이 DB가 막는다(reviews_answer_exactly_one_value)."""
        blank = ReviewSubmission.objects.create(
            round=self.round,
            evaluator=self.participants[1],
            review_type=ReviewSubmission.ReviewType.TEAM,
            target_team=self.team_two,
        )

        with self.assertRaises(IntegrityError):
            ReviewAnswer.objects.create(
                submission=blank, question=self.text_question, text_value=""
            )

    def test_progress_page_links_to_the_answers_screen(self):
        self.client.force_login(self.tutor)

        response = self.client.get(reverse("rounds:reviews", args=(self.round.pk,)))

        self.assertContains(response, self.url)
        self.assertEqual(response.context["text_answer_count"], 1)


class QuestionRowAddingTests(TestCase):
    """문항 줄 추가 - 빈 행 3개 제한 때문에 저장·재편집을 반복해야 했다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="rows-tutor@example.com",
            password="strong-test-password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.tutor)

    def test_form_ships_an_empty_row_template_and_add_button(self):
        response = self.client.get(reverse("rounds:template-create"))

        self.assertContains(response, 'id="addQuestionRow"')
        self.assertContains(response, 'id="questionRowTemplate"')
        self.assertContains(response, "__prefix__")

    def test_more_rows_than_the_default_extra_are_saved(self):
        """폼셋 개수를 늘려 보내면 기본 빈 행(3개)보다 많이 저장돼야 한다."""
        prompts = [f"문항 {index}" for index in range(1, 6)]
        payload = {
            "name": "다문항 템플릿",
            "description": "",
            "category": QuestionTemplate.Category.TEAM,
            "questions-TOTAL_FORMS": str(len(prompts)),
            "questions-INITIAL_FORMS": "0",
            "questions-MIN_NUM_FORMS": "0",
            "questions-MAX_NUM_FORMS": "1000",
        }
        for index, prompt in enumerate(prompts):
            payload[f"questions-{index}-prompt"] = prompt
            payload[f"questions-{index}-response_type"] = (
                TemplateQuestion.ResponseType.RATING_5
                if index < 3
                else TemplateQuestion.ResponseType.TEXT
            )
            payload[f"questions-{index}-is_required"] = "on"

        response = self.client.post(reverse("rounds:template-create"), payload)

        self.assertRedirects(response, reverse("rounds:template-list"))
        template = QuestionTemplate.objects.get(name="다문항 템플릿")
        self.assertEqual(
            [question.prompt for question in template.questions.order_by("display_order")],
            prompts,
        )


class QuestionTemplateDeletionTests(TestCase):
    """복제한 템플릿이 있으면 원본 삭제가 500이 아니라 안내 메시지로 막혀야 한다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="tpl-del-tutor@example.com",
            password="strong-test-password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.template = QuestionTemplate.objects.create(
            name="원본 템플릿", category="TEAM", created_by=self.tutor
        )
        TemplateQuestion.objects.create(
            template=self.template, response_type="RATING_5", prompt="문항", display_order=1
        )
        self.client.force_login(self.tutor)

    def test_template_with_copies_is_not_deleted(self):
        self.client.post(reverse("rounds:template-copy", kwargs={"template_id": self.template.pk}))

        response = self.client.post(
            reverse("rounds:template-delete", kwargs={"template_id": self.template.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(QuestionTemplate.objects.filter(pk=self.template.pk).exists())
        self.assertContains(response, "복제본을 먼저 삭제해 주세요")

    def test_template_without_copies_is_deleted(self):
        response = self.client.post(
            reverse("rounds:template-delete", kwargs={"template_id": self.template.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(QuestionTemplate.objects.filter(pk=self.template.pk).exists())

    def test_delete_button_is_disabled_for_a_copied_template(self):
        self.client.post(reverse("rounds:template-copy", kwargs={"template_id": self.template.pk}))

        response = self.client.get(reverse("rounds:template-list"))

        self.assertContains(response, "복제본을 먼저 삭제해 주세요")


class TutorPeerReviewTests(TestCase):
    """튜터 개인평가 - 튜터가 수강생을 직접 평가하고 언제든 고쳐 쓸 수 있어야 한다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="tpr-tutor@example.com",
            password="strong-test-password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.student = User.objects.create_user(
            email="tpr-student@example.com",
            password="strong-test-password",
            first_name="학생",
            student_number="T100",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True,
        )
        self.peer_template = QuestionTemplate.objects.create(
            name="개인 평가", category="PEER", created_by=self.tutor
        )
        self.question = TemplateQuestion.objects.create(
            template=self.peer_template,
            response_type="RATING_5",
            prompt="맡은 일을 끝까지 해냈나요?",
            display_order=1,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="튜터 평가 회차",
            status=EvaluationRound.Status.IN_PROGRESS,
            evaluation_start_at=now - timedelta(hours=1),
            evaluation_end_at=now + timedelta(days=1),
            peer_template=self.peer_template,
            created_by=self.tutor,
            started_at=now - timedelta(hours=1),
        )
        self.participant = RoundParticipant.objects.create(
            round=self.round,
            user=self.student,
            student_number_snapshot=self.student.student_number,
            display_name_snapshot=self.student.first_name,
        )

    def _form_url(self):
        return reverse(
            "rounds:tutor-review-form",
            kwargs={"round_id": self.round.pk, "participant_id": self.participant.pk},
        )

    def test_tutor_can_write_and_rewrite_a_peer_review(self):
        self.client.force_login(self.tutor)

        self.client.post(self._form_url(), {f"question_{self.question.pk}": "4"})

        review = TutorReview.objects.get(round=self.round, target_participant=self.participant)
        self.assertEqual(review.evaluator, self.tutor)
        self.assertEqual(review.answers.get().rating_value, 4)

        self.client.post(self._form_url(), {f"question_{self.question.pk}": "5"})

        self.assertEqual(TutorReview.objects.count(), 1)
        self.assertEqual(review.answers.get().rating_value, 5)

    def test_students_cannot_open_tutor_peer_review(self):
        self.client.force_login(self.student)

        response = self.client.get(self._form_url())

        self.assertEqual(response.status_code, 403)
        self.assertFalse(TutorReview.objects.exists())

    def test_draft_round_cannot_be_reviewed_yet(self):
        # 준비 중 회차는 참가자와 질문지가 아직 바뀔 수 있어 평가를 받지 않는다.
        self.round.status = EvaluationRound.Status.DRAFT
        self.round.save(update_fields=["status"])
        self.client.force_login(self.tutor)

        response = self.client.post(self._form_url(), {f"question_{self.question.pk}": "4"})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(TutorReview.objects.exists())

    def test_tutor_review_is_not_counted_as_a_student_peer_review(self):
        self.client.force_login(self.tutor)

        self.client.post(self._form_url(), {f"question_{self.question.pk}": "4"})

        self.assertFalse(ReviewSubmission.objects.exists())


class RoundFormTests(TestCase):
    """회차 설정 - 목표 팀 수 없이 저장되고 참가자는 승인된 수강생 전원이 된다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="rf-tutor@example.com",
            password="strong-test-password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.approved = [
            User.objects.create_user(
                email=f"rf-student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"RF{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
            )
            for index in range(1, 4)
        ]
        self.pending = User.objects.create_user(
            email="rf-pending@example.com",
            password="strong-test-password",
            first_name="대기",
            student_number="RF900",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.PENDING,
        )
        self.client.force_login(self.tutor)

    def test_saving_a_round_adds_every_approved_student(self):
        now = timezone.now()
        response = self.client.post(
            reverse("rounds:create"),
            {
                "title": "자동 참가자 회차",
                "description": "",
                "evaluation_start_at": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "evaluation_end_at": (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            },
        )

        created = EvaluationRound.objects.get(title="자동 참가자 회차")
        self.assertRedirects(response, reverse("rounds:teams", kwargs={"round_id": created.pk}))
        self.assertEqual(created.participants.count(), len(self.approved))
        self.assertFalse(created.participants.filter(user=self.pending).exists())

    def test_existing_participant_is_kept_even_if_no_longer_eligible(self):
        """비활성이 된 참가자를 자동으로 빼면 팀 배정 때문에 저장이 막힌다(회귀 방지)."""
        now = timezone.now()
        round_obj = EvaluationRound.objects.create(
            title="기존 참가자 회차",
            evaluation_start_at=now + timedelta(days=1),
            evaluation_end_at=now + timedelta(days=2),
            created_by=self.tutor,
        )
        leaver = self.approved[0]
        participant = RoundParticipant.objects.create(
            round=round_obj,
            user=leaver,
            student_number_snapshot=leaver.student_number,
            display_name_snapshot=leaver.first_name,
        )
        team = Team.objects.create(round=round_obj, team_number=1, name="1팀")
        TeamMembership.objects.create(team=team, participant=participant)
        leaver.is_active = False
        leaver.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("rounds:edit", kwargs={"round_id": round_obj.pk}),
            {
                "title": "기존 참가자 회차",
                "description": "",
                "evaluation_start_at": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "evaluation_end_at": (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(round_obj.participants.filter(user=leaver).exists())

    def test_round_form_no_longer_shows_target_team_count(self):
        response = self.client.get(reverse("rounds:create"))

        self.assertNotContains(response, "목표 팀 수")
        self.assertContains(response, "참가 수강생은")

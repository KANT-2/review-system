from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from results.application import calculate_round, toggle_publication
from results.models import CalculationRun, EvaluationResult
from reviews.models import ReviewAnswer, ReviewSubmission
from rounds.models import EvaluationRound, QuestionTemplate, RoundParticipant, TemplateQuestion
from teams.models import Team, TeamMembership


class ResultWorkflowTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="result-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.students = [
            User.objects.create_user(
                email=f"result-student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"P{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
            )
            for index in range(1, 5)
        ]
        team_template = QuestionTemplate.objects.create(
            name="결과 팀", category="TEAM", created_by=self.tutor
        )
        peer_template = QuestionTemplate.objects.create(
            name="결과 개인", category="PEER", created_by=self.tutor
        )
        self.team_question = TemplateQuestion.objects.create(
            template=team_template,
            response_type="RATING_5",
            prompt="팀 완성도",
            display_order=1,
        )
        self.peer_question = TemplateQuestion.objects.create(
            template=peer_template,
            response_type="RATING_5",
            prompt="개인 기여도",
            display_order=1,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="결과 회차",
            status=EvaluationRound.Status.COMPLETED,
            evaluation_start_at=now - timedelta(days=2),
            evaluation_end_at=now - timedelta(days=1),
            target_team_count=2,
            team_template=team_template,
            peer_template=peer_template,
            created_by=self.tutor,
            started_at=now - timedelta(days=2),
            completed_at=now,
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
        self.teams = [
            Team.objects.create(round=self.round, team_number=index, name=f"{index}팀")
            for index in (1, 2)
        ]
        for participant in self.participants[:2]:
            TeamMembership.objects.create(team=self.teams[0], participant=participant)
        for participant in self.participants[2:]:
            TeamMembership.objects.create(team=self.teams[1], participant=participant)
        self._create_complete_submissions()

    def _answer(self, submission, question, rating):
        ReviewAnswer.objects.create(
            submission=submission,
            question=question,
            rating_value=rating,
        )

    def _create_complete_submissions(self):
        for participant in self.participants[:2]:
            submission = ReviewSubmission.objects.create(
                round=self.round,
                review_type="TEAM",
                evaluator=participant,
                target_team=self.teams[1],
            )
            self._answer(submission, self.team_question, 5)
        for participant in self.participants[2:]:
            submission = ReviewSubmission.objects.create(
                round=self.round,
                review_type="TEAM",
                evaluator=participant,
                target_team=self.teams[0],
            )
            self._answer(submission, self.team_question, 4)
        peer_pairs = ((0, 1), (1, 0), (2, 3), (3, 2))
        for evaluator_index, target_index in peer_pairs:
            submission = ReviewSubmission.objects.create(
                round=self.round,
                review_type="PEER",
                evaluator=self.participants[evaluator_index],
                target_participant=self.participants[target_index],
            )
            self._answer(submission, self.peer_question, 4)

    def test_calculation_creates_active_version_and_real_student_page(self):
        run = calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.assertTrue(run.is_active)
        self.assertEqual(run.status, CalculationRun.Status.SUCCEEDED)
        self.assertEqual(run.results.count(), 6)
        self.assertFalse(run.results.filter(display_score__isnull=True).exists())

        self.client.force_login(self.students[0])
        private_page = self.client.get(reverse("results:me"))
        self.assertContains(private_page, "비공개")

        toggle_publication(
            round_id=self.round.pk,
            item_key="my_score",
            actor=self.tutor,
        )
        public_page = self.client.get(reverse("results:me"))
        self.assertContains(public_page, "내 점수 구성")
        self.assertContains(public_page, "4.0/5")

        mypage = self.client.get(reverse("accounts:mypage"))
        self.assertContains(mypage, "팀 40% + 개인 60%")
        self.assertContains(mypage, '4.0<small class="fs-6">/5</small>', html=True)
        self.assertNotContains(mypage, "다음 회차 편성 기준 점수")

    def test_recalculation_replaces_active_run_and_resets_publication(self):
        first = calculate_round(round_id=self.round.pk, actor=self.tutor)
        toggle_publication(
            round_id=self.round.pk,
            item_key="team_ranking",
            actor=self.tutor,
        )
        second = calculate_round(round_id=self.round.pk, actor=self.tutor)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertIsNone(second.team_ranking_published_at)

    def test_partial_publication_requires_confirmation(self):
        ReviewSubmission.objects.filter(review_type="TEAM").first().delete()
        run = calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.assertTrue(
            run.results.filter(data_status=EvaluationResult.DataStatus.PARTIAL).exists()
        )
        with self.assertRaises(ValidationError):
            toggle_publication(
                round_id=self.round.pk,
                item_key="my_score",
                actor=self.tutor,
            )

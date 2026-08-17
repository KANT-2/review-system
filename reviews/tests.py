from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from reviews.models import ReviewAnswer, ReviewSubmission
from rounds.models import EvaluationRound, QuestionTemplate, RoundParticipant, TemplateQuestion
from teams.models import Team, TeamMembership


class ReviewPageTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="tutor-pages@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.students = [
            User.objects.create_user(
                email=f"student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"S{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
            )
            for index in range(1, 5)
        ]
        self.team_template = QuestionTemplate.objects.create(
            name="팀 기본",
            category=QuestionTemplate.Category.TEAM,
            created_by=self.tutor,
        )
        self.team_question = TemplateQuestion.objects.create(
            template=self.team_template,
            response_type=TemplateQuestion.ResponseType.RATING_5,
            prompt="완성도는 어떤가요?",
            display_order=1,
        )
        self.peer_template = QuestionTemplate.objects.create(
            name="개인 기본",
            category=QuestionTemplate.Category.PEER,
            created_by=self.tutor,
        )
        self.peer_question = TemplateQuestion.objects.create(
            template=self.peer_template,
            response_type=TemplateQuestion.ResponseType.RATING_5,
            prompt="기여도는 어떤가요?",
            display_order=1,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="실제 연결 회차",
            status=EvaluationRound.Status.IN_PROGRESS,
            evaluation_start_at=now - timedelta(hours=1),
            evaluation_end_at=now + timedelta(hours=1),
            target_team_count=2,
            team_template=self.team_template,
            peer_template=self.peer_template,
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
        self.team_one = Team.objects.create(round=self.round, team_number=1, name="1팀")
        self.team_two = Team.objects.create(round=self.round, team_number=2, name="2팀")
        for participant in self.participants[:2]:
            TeamMembership.objects.create(team=self.team_one, participant=participant)
        for participant in self.participants[2:]:
            TeamMembership.objects.create(team=self.team_two, participant=participant)
        self.client.force_login(self.students[0])

    def test_team_list_excludes_own_team_and_submission_is_immutable(self):
        response = self.client.get(reverse("reviews:team-list"))
        self.assertContains(response, "2팀")
        self.assertNotContains(response, "1팀 평가")

        url = reverse("reviews:team-form", args=(self.team_two.pk,))
        first = self.client.post(url, {f"question_{self.team_question.pk}": "5"})
        error_message = first.context["form"].errors.as_json() if first.context else ""
        self.assertEqual(first.status_code, 302, error_message)
        self.assertRedirects(first, reverse("reviews:team-list"))
        submission = ReviewSubmission.objects.get(review_type=ReviewSubmission.ReviewType.TEAM)
        self.assertEqual(submission.answers.get().rating_value, 5)

        self.client.post(url, {f"question_{self.team_question.pk}": "1"})
        self.assertEqual(ReviewSubmission.objects.count(), 1)
        self.assertEqual(ReviewAnswer.objects.get().rating_value, 5)

    def test_peer_form_rejects_self_and_other_team(self):
        self.assertEqual(
            self.client.get(
                reverse("reviews:peer-form", args=(self.participants[0].pk,))
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("reviews:peer-form", args=(self.participants[2].pk,))
            ).status_code,
            403,
        )

    def test_peer_submission_and_status_page_use_real_rows(self):
        url = reverse("reviews:peer-form", args=(self.participants[1].pk,))
        response = self.client.post(url, {f"question_{self.peer_question.pk}": "4"})
        error_message = response.context["form"].errors.as_json() if response.context else ""
        self.assertEqual(response.status_code, 302, error_message)
        self.assertRedirects(response, reverse("reviews:peer-list"))
        status = self.client.get(reverse("reviews:status"))
        self.assertContains(status, "1/1")
        self.assertContains(status, "학생2")

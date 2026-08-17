from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from reviews.models import ReviewAnswer, ReviewFinalSubmission, ReviewSubmission
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

    def test_team_list_excludes_own_team_and_submission_is_editable_until_final(self):
        """제출은 대상별 한 건으로 유지하되, 최종 제출 전까지는 덮어쓸 수 있다."""
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
        # 건수는 그대로 한 건, 값만 바뀐다.
        self.assertEqual(ReviewSubmission.objects.count(), 1)
        self.assertEqual(ReviewAnswer.objects.count(), 1)
        self.assertEqual(ReviewAnswer.objects.get().rating_value, 1)

    def test_edit_form_is_prefilled_with_the_previous_answer(self):
        url = reverse("reviews:team-form", args=(self.team_two.pk,))
        self.client.post(url, {f"question_{self.team_question.pk}": "4"})

        response = self.client.get(url)

        field = response.context["form"][f"question_{self.team_question.pk}"]
        self.assertEqual(field.value(), 4)
        self.assertContains(response, "수정 저장")

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


class PastRoundAccessTests(TestCase):
    """지난 회차 조회 - 읽기는 시작된 회차 전체, 쓰기는 여전히 진행 중 회차만."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="past-tutor@example.com",
            password="strong-test-password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.students = [
            User.objects.create_user(
                email=f"past-student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"P{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
                is_onboarded=True,
            )
            for index in range(1, 5)
        ]
        self.team_template = QuestionTemplate.objects.create(
            name="팀", category=QuestionTemplate.Category.TEAM, created_by=self.tutor
        )
        self.team_question = TemplateQuestion.objects.create(
            template=self.team_template,
            response_type=TemplateQuestion.ResponseType.RATING_5,
            prompt="완성도는?",
            display_order=1,
        )
        self.peer_template = QuestionTemplate.objects.create(
            name="개인", category=QuestionTemplate.Category.PEER, created_by=self.tutor
        )
        self.peer_question = TemplateQuestion.objects.create(
            template=self.peer_template,
            response_type=TemplateQuestion.ResponseType.RATING_5,
            prompt="기여도는?",
            display_order=1,
        )
        now = timezone.now()
        self.past_round = self._build_round("지난 회차", now - timedelta(days=30))
        self.past_round.status = EvaluationRound.Status.COMPLETED
        self.past_round.completed_at = now - timedelta(days=20)
        self.past_round.save()
        self.current_round = self._build_round("이번 회차", now - timedelta(hours=1))
        self.current_round.status = EvaluationRound.Status.IN_PROGRESS
        self.current_round.save()
        self.client.force_login(self.students[0])

    def _build_round(self, title, started_at):
        evaluation_round = EvaluationRound.objects.create(
            title=title,
            status=EvaluationRound.Status.DRAFT,
            evaluation_start_at=started_at,
            evaluation_end_at=started_at + timedelta(days=7),
            target_team_count=2,
            team_template=self.team_template,
            peer_template=self.peer_template,
            created_by=self.tutor,
            started_at=started_at,
        )
        participants = [
            RoundParticipant.objects.create(
                round=evaluation_round,
                user=user,
                student_number_snapshot=user.student_number,
                display_name_snapshot=user.first_name,
            )
            for user in self.students
        ]
        team_one = Team.objects.create(round=evaluation_round, team_number=1, name="1팀")
        team_two = Team.objects.create(round=evaluation_round, team_number=2, name="2팀")
        for participant in participants[:2]:
            TeamMembership.objects.create(team=team_one, participant=participant)
        for participant in participants[2:]:
            TeamMembership.objects.create(team=team_two, participant=participant)
        return evaluation_round

    def _submit_past_peer_review(self):
        evaluator = RoundParticipant.objects.get(round=self.past_round, user=self.students[0])
        target = RoundParticipant.objects.get(round=self.past_round, user=self.students[1])
        submission = ReviewSubmission.objects.create(
            round=self.past_round,
            evaluator=evaluator,
            review_type=ReviewSubmission.ReviewType.PEER,
            target_participant=target,
        )
        ReviewAnswer.objects.create(
            submission=submission, question=self.peer_question, rating_value=4
        )
        return submission

    def test_status_page_lets_the_student_switch_to_a_past_round(self):
        response = self.client.get(reverse("reviews:status"), {"round": self.past_round.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["participant"].round_id, self.past_round.pk)
        self.assertFalse(response.context["is_current_round"])

    def test_status_page_defaults_to_the_round_in_progress(self):
        response = self.client.get(reverse("reviews:status"))

        self.assertEqual(response.context["participant"].round_id, self.current_round.pk)
        self.assertTrue(response.context["is_current_round"])

    def test_past_round_offers_no_write_link(self):
        """지난 회차는 조회만 - 미제출 대상에 작성 링크가 나오면 안 된다."""
        past = self.client.get(reverse("reviews:status"), {"round": self.past_round.pk})
        current = self.client.get(reverse("reviews:status"))

        self.assertNotContains(past, ">작성</a>")
        self.assertContains(past, "미제출")
        # 진행 중 회차에서는 그대로 작성할 수 있어야 한다.
        self.assertContains(current, ">작성</a>")

    def test_student_reads_own_past_submission(self):
        submission = self._submit_past_peer_review()

        response = self.client.get(reverse("reviews:submission-detail", args=(submission.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "기여도는?")
        self.assertContains(response, "지난 회차")
        # 제출 시각이 비어 보이지 않아야 한다(필드명을 잘못 쓰면 조용히 빈칸이 된다).
        # 화면은 TIME_ZONE(Asia/Seoul) 기준으로 찍으므로 저장값(UTC)을 그대로 비교하면 안 된다.
        local_submitted_at = timezone.localtime(submission.submitted_at)
        self.assertContains(response, local_submitted_at.strftime("%Y.%m.%d"))

    def test_student_cannot_read_someone_elses_submission(self):
        submission = self._submit_past_peer_review()
        self.client.force_login(self.students[2])

        response = self.client.get(reverse("reviews:submission-detail", args=(submission.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_past_round_write_path_stays_closed(self):
        """조회를 열어도 지난 회차 제출은 계속 막혀 있어야 한다."""
        target = RoundParticipant.objects.get(round=self.past_round, user=self.students[1])

        response = self.client.post(
            reverse("reviews:peer-form", args=(target.pk,)),
            {f"question_{self.peer_question.pk}": "5"},
        )

        self.assertEqual(response.status_code, 403)


class FinalSubmitTests(TestCase):
    """유형별 최종 제출 - 여기까지 마쳐야 평가가 잠긴다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="final-tutor@example.com",
            password="strong-test-password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.students = [
            User.objects.create_user(
                email=f"final-student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"F{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
                is_onboarded=True,
            )
            for index in range(1, 5)
        ]
        team_template = QuestionTemplate.objects.create(
            name="팀", category=QuestionTemplate.Category.TEAM, created_by=self.tutor
        )
        self.team_question = TemplateQuestion.objects.create(
            template=team_template,
            response_type=TemplateQuestion.ResponseType.RATING_5,
            prompt="완성도는?",
            display_order=1,
        )
        peer_template = QuestionTemplate.objects.create(
            name="개인", category=QuestionTemplate.Category.PEER, created_by=self.tutor
        )
        self.peer_question = TemplateQuestion.objects.create(
            template=peer_template,
            response_type=TemplateQuestion.ResponseType.RATING_5,
            prompt="기여도는?",
            display_order=1,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="최종 제출 회차",
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
        self.client.force_login(self.students[0])
        self.url = reverse("reviews:final-submit", args=("TEAM",))

    def _submit_team_review(self, rating="4"):
        return self.client.post(
            reverse("reviews:team-form", args=(self.team_two.pk,)),
            {f"question_{self.team_question.pk}": rating},
        )

    def test_final_submit_is_blocked_until_every_target_is_done(self):
        response = self.client.post(self.url)

        self.assertRedirects(response, reverse("reviews:team-list"))
        self.assertFalse(ReviewFinalSubmission.objects.exists())

    def test_final_submit_locks_the_review_type(self):
        self._submit_team_review("4")

        response = self.client.post(self.url)

        self.assertRedirects(response, reverse("reviews:team-list"))
        self.assertTrue(
            ReviewFinalSubmission.objects.filter(
                round=self.round, evaluator=self.participants[0], review_type="TEAM"
            ).exists()
        )
        # 잠긴 뒤에는 값을 바꿀 수 없다.
        self._submit_team_review("1")
        self.assertEqual(ReviewAnswer.objects.get().rating_value, 4)

    def test_locked_form_is_read_only(self):
        self._submit_team_review("4")
        self.client.post(self.url)

        response = self.client.get(reverse("reviews:team-form", args=(self.team_two.pk,)))

        self.assertTrue(response.context["finalized"])
        self.assertNotContains(response, "수정 저장")

    def test_final_submit_only_locks_its_own_type(self):
        self._submit_team_review("4")
        self.client.post(self.url)

        peer_url = reverse("reviews:peer-form", args=(self.participants[1].pk,))
        response = self.client.post(peer_url, {f"question_{self.peer_question.pk}": "5"})

        self.assertRedirects(response, reverse("reviews:peer-list"))
        self.assertTrue(
            ReviewSubmission.objects.filter(review_type="PEER", evaluator=self.participants[0])
            .first()
            .answers.filter(rating_value=5)
            .exists()
        )

    def test_final_submit_cannot_run_twice(self):
        self._submit_team_review("4")
        self.client.post(self.url)

        self.client.post(self.url)

        self.assertEqual(ReviewFinalSubmission.objects.count(), 1)

    def test_unknown_review_type_is_not_found(self):
        response = self.client.post(reverse("reviews:final-submit", args=("BOGUS",)))

        self.assertEqual(response.status_code, 404)

    def test_final_submit_is_post_only(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

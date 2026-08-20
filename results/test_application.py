from datetime import timedelta
from decimal import Decimal

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from results.application import (
    PUBLICATION_FIELDS,
    calculate_round,
    toggle_all_publications,
    toggle_publication,
)
from results.models import CalculationRun, EvaluationResult, TutorNote
from reviews.models import (
    ReviewAnswer,
    ReviewSubmission,
    TutorReview,
    TutorReviewAnswer,
    TutorTeamReview,
    TutorTeamReviewAnswer,
)
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
                is_onboarded=True,
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
        before_publication = self.client.get(reverse("accounts:mypage"))
        self.assertContains(before_publication, "공개된 평가 결과가 없습니다")

        toggle_publication(
            round_id=self.round.pk,
            item_key="my_score",
            actor=self.tutor,
        )

        mypage = self.client.get(reverse("accounts:mypage"))
        self.assertContains(mypage, "팀 40% · 개인 60%로 계산")
        self.assertContains(mypage, '4.00<small class="fs-6">/5</small>', html=True)
        self.assertNotContains(mypage, "다음 회차 편성 기준 점수")

    def test_tutor_team_review_blends_into_team_score_when_weight_enabled(self):
        # teams[0]은 학생 팀평가만으로는 4.0/5 - 여기에 튜터 팀평가(2점)가 섞이면
        # (4+4+2)/3 = 3.333333으로 내려가야 한다.
        self.round.team_score_weight = 30
        self.round.personal_score_weight = 40
        self.round.tutor_score_weight = 30
        self.round.save(
            update_fields=["team_score_weight", "personal_score_weight", "tutor_score_weight"]
        )
        review = TutorTeamReview.objects.create(
            round=self.round, evaluator=self.tutor, target_team=self.teams[0]
        )
        TutorTeamReviewAnswer.objects.create(
            review=review, question=self.team_question, rating_value=2
        )

        run = calculate_round(round_id=self.round.pk, actor=self.tutor)

        team_result = run.results.get(
            result_type=EvaluationResult.ResultType.TEAM, team=self.teams[0]
        )
        self.assertEqual(team_result.team_score_raw, Decimal("3.333333"))

    def test_tutor_team_review_is_ignored_when_tutor_weight_is_zero(self):
        # 기본값(tutor_score_weight=0)이면 튜터 팀평가가 있어도 학생 평가만으로 계산한다.
        review = TutorTeamReview.objects.create(
            round=self.round, evaluator=self.tutor, target_team=self.teams[0]
        )
        TutorTeamReviewAnswer.objects.create(
            review=review, question=self.team_question, rating_value=2
        )

        run = calculate_round(round_id=self.round.pk, actor=self.tutor)

        team_result = run.results.get(
            result_type=EvaluationResult.ResultType.TEAM, team=self.teams[0]
        )
        self.assertEqual(team_result.team_score_raw, Decimal("4.000000"))

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

    def test_manage_screen_renders_ranking_controls(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)

        response = self.client.get(reverse("rounds:results", kwargs={"round_id": self.round.pk}))

        self.assertContains(response, "ax-rank-badge")  # 순위 배지
        self.assertContains(response, "ax-filter-chip")  # 데이터 상태 필터
        self.assertContains(response, "round-switcher")  # 회차 전환
        self.assertEqual(response.context["summary"]["team_count"], 2)
        self.assertEqual(response.context["summary"]["participant_count"], 4)
        # 화면에 노출되는 가중치는 실제 계산식(RES-004)에서 가져온다.
        self.assertEqual(response.context["team_weight_percent"], 40)
        self.assertEqual(response.context["peer_weight_percent"], 60)

    def test_publish_settings_screen_renders_publish_controls(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)

        response = self.client.get(
            reverse("rounds:publish-settings", kwargs={"round_id": self.round.pk})
        )

        self.assertContains(response, "ax-switch")  # 항목별 공개 토글
        self.assertContains(response, "round-switcher")  # 회차 전환

    def test_results_without_rank_sort_after_ranked_rows(self):
        # 개인 평가를 한 건도 못 받은 학생은 N/A라 순위가 없고, 표 맨 뒤에 와야 한다.
        ReviewSubmission.objects.filter(
            review_type="PEER", target_participant=self.participants[0]
        ).delete()
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)

        response = self.client.get(reverse("rounds:results", kwargs={"round_id": self.round.pk}))

        ranks = [result.primary_rank for result in response.context["individual_results"]]
        self.assertIsNone(ranks[-1])
        self.assertTrue(all(rank is not None for rank in ranks[:-1]))
        self.assertEqual(response.context["summary"]["na_count"], 1)

    def test_publishing_partial_data_asks_for_confirmation_before_publishing(self):
        ReviewSubmission.objects.filter(review_type="TEAM").first().delete()
        run = calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)
        settings_url = reverse("rounds:publish-settings", kwargs={"round_id": self.round.pk})
        publish_url = reverse(
            "rounds:publish-results", kwargs={"round_id": self.round.pk, "item_key": "my_score"}
        )

        first_attempt = self.client.post(publish_url)

        self.assertRedirects(
            first_attempt, f"{settings_url}?confirm=my_score", fetch_redirect_response=False
        )
        run.refresh_from_db()
        self.assertIsNone(run.my_score_published_at)

        confirm_page = self.client.get(f"{settings_url}?confirm=my_score")
        self.assertContains(confirm_page, "예, 공개합니다")
        self.assertEqual(confirm_page.context["pending_confirm"], "my_score")

        confirmed = self.client.post(publish_url, {"partial_confirmed": "1"})

        self.assertRedirects(confirmed, settings_url, fetch_redirect_response=False)
        run.refresh_from_db()
        self.assertIsNotNone(run.my_score_published_at)

    def test_unknown_confirm_query_is_ignored(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)

        response = self.client.get(
            reverse("rounds:publish-settings", kwargs={"round_id": self.round.pk}),
            {"confirm": "<script>"},
        )

        self.assertIsNone(response.context["pending_confirm"])

    def _previous_round_with_scores(self, scores_by_user):
        """이 회차보다 먼저 완료된 회차의 채점 결과를 만들어 둔다 (추이 배지 비교 대상)."""
        now = timezone.now()
        previous_round = EvaluationRound.objects.create(
            title="지난 회차",
            status=EvaluationRound.Status.COMPLETED,
            evaluation_start_at=now - timedelta(days=20),
            evaluation_end_at=now - timedelta(days=15),
            target_team_count=2,
            created_by=self.tutor,
            started_at=now - timedelta(days=20),
            completed_at=now - timedelta(days=15),
        )
        run = CalculationRun.objects.create(
            round=previous_round,
            version=1,
            formula_version="score-v1",
            executed_by=self.tutor,
            status=CalculationRun.Status.SUCCEEDED,
            is_active=True,
            finished_at=now - timedelta(days=15),
        )
        for user, score in scores_by_user.items():
            participant = RoundParticipant.objects.create(
                round=previous_round,
                user=user,
                student_number_snapshot=user.student_number,
                display_name_snapshot=user.first_name,
            )
            EvaluationResult.objects.create(
                calculation_run=run,
                result_type=EvaluationResult.ResultType.INDIVIDUAL,
                participant=participant,
                final_score_raw=score,
                display_score=score,
                expected_count=1,
                valid_count=1,
                data_status=EvaluationResult.DataStatus.COMPLETE,
            )
        return previous_round

    def test_trend_badge_compares_against_the_previous_round(self):
        # 이번 회차 최종점수: 1팀 4.00, 2팀 4.40 - 지난 회차 점수에 따라 방향이 갈린다.
        self._previous_round_with_scores(
            {
                self.students[0]: Decimal("3.50"),  # 1팀 4.00 <- 3.50, 상승
                self.students[1]: Decimal("4.50"),  # 1팀 4.00 <- 4.50, 하락
                self.students[2]: Decimal("4.40"),  # 2팀 4.40 <- 4.40, 변화없음
                # students[3]은 지난 회차 결과가 없어 비교 대상이 아니다.
            }
        )
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)

        response = self.client.get(reverse("rounds:results", kwargs={"round_id": self.round.pk}))

        trends = {
            result.participant.user_id: (result.trend_direction, result.trend_delta)
            for result in response.context["individual_results"]
        }
        self.assertEqual(trends[self.students[0].pk], ("up", Decimal("0.50")))
        self.assertEqual(trends[self.students[1].pk], ("down", Decimal("0.50")))
        self.assertEqual(trends[self.students[2].pk][0], "flat")
        self.assertIsNone(trends[self.students[3].pk][0])

    def test_master_switch_publishes_and_unpublishes_every_item(self):
        run = calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)
        url = reverse("rounds:publish-all-results", kwargs={"round_id": self.round.pk})

        self.client.post(url)

        run.refresh_from_db()
        published = [getattr(run, field) for field in PUBLICATION_FIELDS.values()]
        self.assertTrue(all(published))

        self.client.post(url)

        run.refresh_from_db()
        self.assertTrue(all(getattr(run, field) is None for field in PUBLICATION_FIELDS.values()))

    def test_master_switch_asks_for_confirmation_on_partial_data(self):
        ReviewSubmission.objects.filter(review_type="TEAM").first().delete()
        run = calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)
        settings_url = reverse("rounds:publish-settings", kwargs={"round_id": self.round.pk})
        url = reverse("rounds:publish-all-results", kwargs={"round_id": self.round.pk})

        first_attempt = self.client.post(url)

        self.assertRedirects(
            first_attempt, f"{settings_url}?confirm=ALL", fetch_redirect_response=False
        )
        run.refresh_from_db()
        self.assertIsNone(run.winner_published_at)

        confirm_page = self.client.get(f"{settings_url}?confirm=ALL")
        self.assertContains(confirm_page, "예, 전체 공개합니다")

        self.client.post(url, {"partial_confirmed": "1"})

        run.refresh_from_db()
        self.assertTrue(all(getattr(run, field) for field in PUBLICATION_FIELDS.values()))

    def test_tutor_note_is_appended_to_history_not_overwritten(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)
        url = reverse("accounts:save_student_note", kwargs={"user_id": self.students[0].pk})

        self.client.post(url, {"body": " 개인 사정으로 일부만 제출 "})

        first_note = TutorNote.objects.get(student=self.students[0])
        self.assertEqual(first_note.body, "개인 사정으로 일부만 제출")
        self.assertEqual(first_note.author, self.tutor)

        self.client.post(url, {"body": "다음 회차에 재확인"})

        # 새 메모는 이전 메모를 덮어쓰지 않고 기록으로 쌓인다 - 최신순으로 조회된다.
        notes = list(TutorNote.objects.filter(student=self.students[0]))
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0].body, "다음 회차에 재확인")
        self.assertEqual(notes[1].body, "개인 사정으로 일부만 제출")

        response = self.client.post(url, {"body": "   "})

        # 빈 메모는 저장되지 않고 에러로 되돌아간다 - 더 이상 "비우면 삭제" 동작은 없다.
        self.assertEqual(TutorNote.objects.filter(student=self.students[0]).count(), 2)
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any("입력" in str(message) for message in messages))

    def test_tutor_note_can_be_deleted_individually(self):
        self.client.force_login(self.tutor)
        keep = TutorNote.objects.create(
            student=self.students[0], body="남겨둘 메모", author=self.tutor
        )
        to_delete = TutorNote.objects.create(
            student=self.students[0], body="지울 메모", author=self.tutor
        )

        response = self.client.post(
            reverse(
                "accounts:delete_student_note",
                kwargs={"user_id": self.students[0].pk, "note_id": to_delete.pk},
            )
        )

        self.assertRedirects(response, reverse("accounts:account_admin"))
        remaining = TutorNote.objects.filter(student=self.students[0])
        self.assertEqual(list(remaining), [keep])

    def test_deleting_a_note_requires_it_to_belong_to_the_url_student(self):
        # note_id는 맞지만 URL의 user_id가 다른 학생이면 지워지지 않는다 - 실수로
        # 다른 학생 메모를 지우는 사고를 막는다.
        self.client.force_login(self.tutor)
        note = TutorNote.objects.create(
            student=self.students[0], body="지우면 안 되는 메모", author=self.tutor
        )

        self.client.post(
            reverse(
                "accounts:delete_student_note",
                kwargs={"user_id": self.students[1].pk, "note_id": note.pk},
            )
        )

        self.assertTrue(TutorNote.objects.filter(pk=note.pk).exists())

    def test_all_tutor_notes_for_a_student_can_be_deleted_at_once(self):
        self.client.force_login(self.tutor)
        TutorNote.objects.create(student=self.students[0], body="첫 메모", author=self.tutor)
        TutorNote.objects.create(student=self.students[0], body="둘째 메모", author=self.tutor)
        TutorNote.objects.create(student=self.students[1], body="다른 학생 메모", author=self.tutor)

        response = self.client.post(
            reverse("accounts:delete_all_student_notes", kwargs={"user_id": self.students[0].pk})
        )

        self.assertRedirects(response, reverse("accounts:account_admin"))
        self.assertFalse(TutorNote.objects.filter(student=self.students[0]).exists())
        self.assertTrue(TutorNote.objects.filter(student=self.students[1]).exists())

    def test_students_cannot_delete_tutor_notes(self):
        note = TutorNote.objects.create(
            student=self.students[0], body="학생이 못 지우는 메모", author=self.tutor
        )
        self.client.force_login(self.students[0])

        response = self.client.post(
            reverse(
                "accounts:delete_student_note",
                kwargs={"user_id": self.students[0].pk, "note_id": note.pk},
            )
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(TutorNote.objects.filter(pk=note.pk).exists())

    def test_tutor_note_never_reaches_the_student_page(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        TutorNote.objects.create(
            student=self.students[0], body="학생에게 보이면 안 되는 메모", author=self.tutor
        )
        toggle_publication(round_id=self.round.pk, item_key="my_score", actor=self.tutor)
        self.client.force_login(self.students[0])

        response = self.client.get(reverse("accounts:mypage"))

        self.assertNotContains(response, "학생에게 보이면 안 되는 메모")

    def test_published_but_missing_values_are_not_labelled_as_unpublished(self):
        # 개인 평가를 한 건도 못 받은 학생은 공개된 뒤에도 점수가 없다 - 이때 "비공개"가
        # 아니라 데이터가 없다는 뜻의 N/A가 나와야 한다.
        ReviewSubmission.objects.filter(
            review_type="PEER", target_participant=self.participants[0]
        ).delete()
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        toggle_all_publications(round_id=self.round.pk, actor=self.tutor, partial_confirmed=True)
        self.client.force_login(self.students[0])

        response = self.client.get(reverse("accounts:mypage"))

        self.assertContains(response, "N/A")
        self.assertNotContains(response, "비공개")

    def test_students_cannot_write_tutor_notes(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.students[0])

        response = self.client.post(
            reverse("accounts:save_student_note", kwargs={"user_id": self.students[0].pk}),
            {"body": "내가 쓰면 안 되는 메모"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(TutorNote.objects.exists())

    def test_note_for_a_non_student_account_is_rejected(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)

        self.client.post(
            reverse("accounts:save_student_note", kwargs={"user_id": self.tutor.pk}),
            {"body": "수강생이 아닌 계정"},
        )

        self.assertFalse(TutorNote.objects.exists())

    def test_mypage_shows_team_winner_only_after_publication(self):
        run = calculate_round(round_id=self.round.pk, actor=self.tutor)
        toggle_publication(round_id=self.round.pk, item_key="my_score", actor=self.tutor)
        self.client.force_login(self.students[0])

        before = self.client.get(reverse("accounts:mypage"))
        self.assertContains(before, "비공개")  # 1등 팀은 아직 공개 전

        toggle_publication(round_id=self.round.pk, item_key="team_winner", actor=self.tutor)
        winner = run.results.select_related("team").get(
            result_type=EvaluationResult.ResultType.TEAM, primary_rank=1
        )

        after = self.client.get(reverse("accounts:mypage"))
        self.assertContains(after, winner.team.name)


class StudentResultRoundSelectionTests(TestCase):
    """마이페이지 결과 - 채점이 끝난 회차를 골라서 볼 수 있어야 한다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="sel-tutor@example.com",
            password="strong-test-password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.student = User.objects.create_user(
            email="sel-student@example.com",
            password="strong-test-password",
            first_name="학생",
            student_number="S900",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True,
        )
        self.older = self._completed_round("1회차", days_ago=30, score=Decimal("3.00"))
        self.newer = self._completed_round("2회차", days_ago=5, score=Decimal("4.50"))
        self.client.force_login(self.student)

    def _completed_round(self, title, *, days_ago, score):
        now = timezone.now()
        evaluation_round = EvaluationRound.objects.create(
            title=title,
            status=EvaluationRound.Status.COMPLETED,
            evaluation_start_at=now - timedelta(days=days_ago + 5),
            evaluation_end_at=now - timedelta(days=days_ago + 1),
            target_team_count=2,
            created_by=self.tutor,
            started_at=now - timedelta(days=days_ago + 5),
            completed_at=now - timedelta(days=days_ago),
        )
        run = CalculationRun.objects.create(
            round=evaluation_round,
            version=1,
            formula_version="score-v1",
            executed_by=self.tutor,
            status=CalculationRun.Status.SUCCEEDED,
            is_active=True,
            finished_at=now - timedelta(days=days_ago),
            my_score_published_at=now - timedelta(days=days_ago),
        )
        participant = RoundParticipant.objects.create(
            round=evaluation_round,
            user=self.student,
            student_number_snapshot=self.student.student_number,
            display_name_snapshot=self.student.first_name,
        )
        EvaluationResult.objects.create(
            calculation_run=run,
            result_type=EvaluationResult.ResultType.INDIVIDUAL,
            participant=participant,
            final_score_raw=score,
            display_score=score,
            expected_count=1,
            valid_count=1,
            data_status=EvaluationResult.DataStatus.COMPLETE,
        )
        return evaluation_round

    def test_defaults_to_the_most_recent_completed_round(self):
        response = self.client.get(reverse("accounts:mypage"))

        portal = response.context["portal"]
        self.assertEqual(portal["selected"]["round_id"], self.newer.pk)
        self.assertEqual(len(portal["round_options"]), 2)

    def test_student_can_open_an_older_round(self):
        response = self.client.get(reverse("accounts:mypage"), {"round": self.older.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["portal"]["selected"]["round_id"], self.older.pk)
        self.assertContains(response, "1회차")

    def test_change_against_the_previous_round_is_shown(self):
        response = self.client.get(reverse("accounts:mypage"))

        delta = response.context["portal"]["deltas"]["final_score"]
        self.assertEqual(delta["direction"], "up")
        self.assertEqual(delta["value"], Decimal("1.50"))
        self.assertContains(response, "전 회차 대비 상승")

    def test_first_round_has_nothing_to_compare(self):
        response = self.client.get(reverse("accounts:mypage"), {"round": self.older.pk})

        self.assertIsNone(response.context["portal"]["deltas"]["final_score"])

    def test_old_my_results_url_redirects_to_mypage(self):
        response = self.client.get(reverse("results:me"), {"round": self.older.pk})

        self.assertRedirects(response, f"{reverse('accounts:mypage')}?round={self.older.pk}")

    def test_round_a_student_did_not_join_falls_back_to_their_own(self):
        """남의 회차 id를 넣어도 본인이 참가한 회차만 열린다."""
        outsider_round = EvaluationRound.objects.create(
            title="남의 회차",
            status=EvaluationRound.Status.COMPLETED,
            evaluation_start_at=timezone.now() - timedelta(days=3),
            evaluation_end_at=timezone.now() - timedelta(days=2),
            target_team_count=2,
            created_by=self.tutor,
            completed_at=timezone.now() - timedelta(days=2),
        )

        response = self.client.get(reverse("accounts:mypage"), {"round": outsider_round.pk})

        self.assertEqual(response.context["portal"]["selected"]["round_id"], self.newer.pk)


class TutorWeightScoringTests(TestCase):
    """회차별 점수 반영 비율(팀/개인/튜터) - 기본값은 기존 계산식과 동일해야 한다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="weight-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.students = [
            User.objects.create_user(
                email=f"weight-student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"W{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
                is_onboarded=True,
            )
            for index in range(1, 5)
        ]
        team_template = QuestionTemplate.objects.create(
            name="비율 팀", category="TEAM", created_by=self.tutor
        )
        peer_template = QuestionTemplate.objects.create(
            name="비율 개인", category="PEER", created_by=self.tutor
        )
        self.team_question = TemplateQuestion.objects.create(
            template=team_template, response_type="RATING_5", prompt="팀 완성도", display_order=1
        )
        self.peer_question = TemplateQuestion.objects.create(
            template=peer_template, response_type="RATING_5", prompt="개인 기여도", display_order=1
        )
        self.peer_template = peer_template
        self.team_template = team_template

    def _make_round(self, **weight_kwargs):
        now = timezone.now()
        round_obj = EvaluationRound.objects.create(
            title="비율 회차",
            status=EvaluationRound.Status.COMPLETED,
            evaluation_start_at=now - timedelta(days=2),
            evaluation_end_at=now - timedelta(days=1),
            target_team_count=2,
            team_template=self.team_template,
            peer_template=self.peer_template,
            created_by=self.tutor,
            started_at=now - timedelta(days=2),
            completed_at=now,
            **weight_kwargs,
        )
        participants = [
            RoundParticipant.objects.create(
                round=round_obj,
                user=user,
                student_number_snapshot=user.student_number,
                display_name_snapshot=user.first_name,
            )
            for user in self.students
        ]
        team_a = Team.objects.create(round=round_obj, team_number=1, name="1팀")
        team_b = Team.objects.create(round=round_obj, team_number=2, name="2팀")
        team_a_members = participants[:2]
        team_b_members = participants[2:]
        for participant in team_a_members:
            TeamMembership.objects.create(team=team_a, participant=participant)
        for participant in team_b_members:
            TeamMembership.objects.create(team=team_b, participant=participant)

        for participant in team_a_members:
            submission = ReviewSubmission.objects.create(
                round=round_obj, review_type="TEAM", evaluator=participant, target_team=team_b
            )
            ReviewAnswer.objects.create(
                submission=submission, question=self.team_question, rating_value=4
            )
        for participant in team_b_members:
            submission = ReviewSubmission.objects.create(
                round=round_obj, review_type="TEAM", evaluator=participant, target_team=team_a
            )
            ReviewAnswer.objects.create(
                submission=submission, question=self.team_question, rating_value=4
            )
        peer_pairs = ((0, 1), (1, 0), (2, 3), (3, 2))
        for evaluator_index, target_index in peer_pairs:
            submission = ReviewSubmission.objects.create(
                round=round_obj,
                review_type="PEER",
                evaluator=participants[evaluator_index],
                target_participant=participants[target_index],
            )
            ReviewAnswer.objects.create(
                submission=submission, question=self.peer_question, rating_value=2
            )
        return round_obj, participants

    def _add_tutor_review(self, round_obj, target_participant, rating):
        review = TutorReview.objects.create(
            round=round_obj, evaluator=self.tutor, target_participant=target_participant
        )
        TutorReviewAnswer.objects.create(
            review=review, question=self.peer_question, rating_value=rating
        )

    def test_default_weights_match_the_existing_formula(self):
        round_obj, _participants = self._make_round()

        run = calculate_round(round_id=round_obj.pk, actor=self.tutor)

        individual = run.results.filter(result_type=EvaluationResult.ResultType.INDIVIDUAL).first()
        # 팀 4점 * 40% + 개인 2점 * 60% = 2.8
        self.assertEqual(individual.final_score_raw, Decimal("2.800000"))

    def test_tutor_score_is_ignored_when_weight_is_zero(self):
        round_obj, participants = self._make_round()
        self._add_tutor_review(round_obj, participants[0], rating=5)

        run = calculate_round(round_id=round_obj.pk, actor=self.tutor)

        individual = run.results.get(participant=participants[0])
        self.assertIsNone(individual.tutor_score_raw)
        self.assertEqual(individual.final_score_raw, Decimal("2.800000"))

    def test_custom_weights_change_the_final_score(self):
        round_obj, participants = self._make_round(
            team_score_weight=30, personal_score_weight=40, tutor_score_weight=30
        )
        self._add_tutor_review(round_obj, participants[0], rating=5)
        self._add_tutor_review(round_obj, participants[1], rating=5)

        run = calculate_round(round_id=round_obj.pk, actor=self.tutor)

        individual = run.results.get(participant=participants[0])
        self.assertEqual(individual.tutor_score_raw, Decimal("5.000000"))
        # 팀 4점 * 30% + 개인 2점 * 40% + 튜터 5점 * 30% = 3.5
        self.assertEqual(individual.final_score_raw, Decimal("3.500000"))

    def test_weight_ratio_must_sum_to_100(self):
        now = timezone.now()
        with self.assertRaises(ValidationError):
            EvaluationRound(
                title="잘못된 비율",
                evaluation_start_at=now,
                evaluation_end_at=now + timedelta(days=1),
                created_by=self.tutor,
                team_score_weight=50,
                personal_score_weight=50,
                tutor_score_weight=10,
            ).full_clean()

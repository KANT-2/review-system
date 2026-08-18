from datetime import timedelta
from decimal import Decimal

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
        private_page = self.client.get(reverse("results:me"))
        self.assertContains(private_page, "비공개")

        toggle_publication(
            round_id=self.round.pk,
            item_key="my_score",
            actor=self.tutor,
        )
        public_page = self.client.get(reverse("results:me"))
        self.assertContains(public_page, "내 점수 구성")
        self.assertContains(public_page, "4.00/5")

        mypage = self.client.get(reverse("accounts:mypage"))
        self.assertContains(mypage, "팀 40% + 개인 60%")
        self.assertContains(mypage, '4.00<small class="fs-6">/5</small>', html=True)
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

    def test_tutor_note_is_saved_updated_and_cleared(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.tutor)
        url = reverse(
            "rounds:save-student-note",
            kwargs={"round_id": self.round.pk, "participant_id": self.participants[0].pk},
        )

        self.client.post(url, {"body": " 개인 사정으로 일부만 제출 "})

        note = TutorNote.objects.get(participant=self.participants[0])
        self.assertEqual(note.body, "개인 사정으로 일부만 제출")
        self.assertEqual(note.author, self.tutor)

        self.client.post(url, {"body": "다음 회차에 재확인"})

        self.assertEqual(TutorNote.objects.count(), 1)
        note.refresh_from_db()
        self.assertEqual(note.body, "다음 회차에 재확인")

        self.client.post(url, {"body": "   "})

        self.assertFalse(TutorNote.objects.exists())

    def test_tutor_note_never_reaches_the_student_page(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        TutorNote.objects.create(
            participant=self.participants[0], body="학생에게 보이면 안 되는 메모", author=self.tutor
        )
        toggle_publication(round_id=self.round.pk, item_key="my_score", actor=self.tutor)
        self.client.force_login(self.students[0])

        response = self.client.get(reverse("results:me"))

        self.assertNotContains(response, "학생에게 보이면 안 되는 메모")

    def test_published_but_missing_values_are_not_labelled_as_unpublished(self):
        # 개인 평가를 한 건도 못 받은 학생은 공개된 뒤에도 순위가 없다 - 이때 "비공개"가
        # 아니라 순위 대상이 아니라는 안내가 나와야 한다.
        ReviewSubmission.objects.filter(
            review_type="PEER", target_participant=self.participants[0]
        ).delete()
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        toggle_all_publications(round_id=self.round.pk, actor=self.tutor, partial_confirmed=True)
        self.client.force_login(self.students[0])

        response = self.client.get(reverse("results:me"))

        self.assertContains(response, "순위 없음")
        self.assertContains(response, "받은 개인 평가가 없어 순위 계산에서 빠졌습니다")
        self.assertNotContains(response, "비공개")

    def test_students_cannot_write_tutor_notes(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        self.client.force_login(self.students[0])

        response = self.client.post(
            reverse(
                "rounds:save-student-note",
                kwargs={"round_id": self.round.pk, "participant_id": self.participants[0].pk},
            ),
            {"body": "내가 쓰면 안 되는 메모"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(TutorNote.objects.exists())

    def test_note_for_another_round_participant_is_rejected(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        other_round = self._previous_round_with_scores({self.students[0]: Decimal("3.50")})
        outsider = RoundParticipant.objects.get(round=other_round, user=self.students[0])
        self.client.force_login(self.tutor)

        self.client.post(
            reverse(
                "rounds:save-student-note",
                kwargs={"round_id": self.round.pk, "participant_id": outsider.pk},
            ),
            {"body": "다른 회차 참가자"},
        )

        self.assertFalse(TutorNote.objects.exists())

    def test_student_page_marks_own_team_and_hides_unpublished_items(self):
        calculate_round(round_id=self.round.pk, actor=self.tutor)
        toggle_publication(round_id=self.round.pk, item_key="team_ranking", actor=self.tutor)
        self.client.force_login(self.students[0])

        response = self.client.get(reverse("results:me"))

        self.assertContains(response, "ax-my-team-row")  # 내 팀 강조
        self.assertContains(response, "내 팀")
        self.assertContains(response, "비공개")  # 내 최종점수는 아직 비공개
        self.assertEqual(response.context["my_team_id"], self.teams[0].pk)


class StudentResultRoundSelectionTests(TestCase):
    """내 결과 - 채점이 끝난 회차를 골라서 볼 수 있어야 한다."""

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
        response = self.client.get(reverse("results:me"))

        self.assertEqual(response.context["participant"].round_id, self.newer.pk)
        self.assertEqual(len(response.context["available_rounds"]), 2)

    def test_student_can_open_an_older_round(self):
        response = self.client.get(reverse("results:me"), {"round": self.older.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["participant"].round_id, self.older.pk)
        self.assertContains(response, "1회차")

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

        response = self.client.get(reverse("results:me"), {"round": outsider_round.pk})

        self.assertEqual(response.context["participant"].round_id, self.newer.pk)

from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from results.services import (
    calculate_coverage,
    calculate_final_score,
    calculate_peer_score,
    calculate_seed,
    calculate_team_score,
    competition_rank,
    compute_input_digest,
    determine_data_status,
    reveal_if_published,
    round_to_display,
    round_to_raw,
    score_from_answers,
)


class ResultsPreviewViewTests(TestCase):
    def test_manage_preview_renders(self):
        response = self.client.get(reverse("results:manage_preview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "결과·공개")

    def test_me_preview_renders(self):
        response = self.client.get(reverse("results:me_preview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "내 결과")


class TogglePublishAllTests(TestCase):
    """마스터 스위치(RES-010 4개 항목 일괄 전환)가 개별 항목 토글 라우트
    (preview/publish/<item_key>/toggle/)에 가려지지 않고 제 라우트로 도착하는지도
    같이 검증한다 - urls.py에서 순서가 바뀌면 "all"이 item_key로 오인식된다."""

    def test_turning_on_with_partial_data_requires_confirmation(self):
        response = self.client.post(reverse("results:toggle_publish_all"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get("pending_confirm"), "ALL")
        self.assertFalse(all(self.client.session.get("publish_state", {}).values()))

    def test_confirmed_turns_on_all_four_items(self):
        self.client.post(reverse("results:toggle_publish_all"), {"confirm": "1"})

        publish_state = self.client.session.get("publish_state")
        self.assertTrue(all(publish_state.values()))
        self.assertIsNone(self.client.session.get("pending_confirm"))

    def test_turning_off_does_not_require_confirmation(self):
        self.client.post(reverse("results:toggle_publish_all"), {"confirm": "1"})

        response = self.client.post(reverse("results:toggle_publish_all"))

        self.assertEqual(response.status_code, 302)
        publish_state = self.client.session.get("publish_state")
        self.assertFalse(any(publish_state.values()))


class SaveStudentNoteTests(TestCase):
    def test_saves_note_in_session(self):
        self.client.post(
            reverse("results:save_student_note"), {"student_name": "학생C", "note": "테스트 메모"}
        )

        self.assertEqual(self.client.session.get("student_notes"), {"학생C": "테스트 메모"})

    def test_empty_note_removes_existing_entry(self):
        self.client.post(
            reverse("results:save_student_note"), {"student_name": "학생C", "note": "메모"}
        )
        self.client.post(
            reverse("results:save_student_note"), {"student_name": "학생C", "note": ""}
        )

        self.assertNotIn("학생C", self.client.session.get("student_notes", {}))


class ScoreFromAnswersTests(SimpleTestCase):
    def test_matches_requirements_worked_example(self):
        # docs/REQUIREMENTS.md 예시: [5,4,4,5,4] -> 평균 4.4 -> 88점
        self.assertEqual(score_from_answers([5, 4, 4, 5, 4]), Decimal("88.000000"))

    def test_all_max_answers_gives_100(self):
        self.assertEqual(score_from_answers([5, 5, 5, 5, 5]), Decimal("100.000000"))

    def test_all_min_answers_gives_20_not_zero(self):
        self.assertEqual(score_from_answers([1, 1, 1, 1, 1]), Decimal("20.000000"))


class CalculateTeamScoreTests(SimpleTestCase):
    def test_averages_every_received_team_review(self):
        received = [
            [5, 4, 4, 5, 4],
            [5, 5, 4, 5, 4],
            [4, 4, 3, 4, 4],
            [4, 4, 4, 5, 4],
        ]  # 88,92,76,84
        self.assertEqual(calculate_team_score(received), Decimal("85.000000"))

    def test_is_na_when_team_received_no_reviews(self):
        # RES-002 / SUB-006: N/A, not 0.00
        self.assertIsNone(calculate_team_score([]))


class CalculatePeerScoreTests(SimpleTestCase):
    def test_averages_every_received_peer_review(self):
        received = [[5, 4, 5, 4], [4, 4, 4, 4, 4], [5, 5, 5, 5, 5]]  # 90, 80, 100
        self.assertEqual(calculate_peer_score(received), Decimal("90.000000"))

    def test_is_na_when_student_received_no_reviews(self):
        # RES-003 / SUB-006: N/A, not 0.00
        self.assertIsNone(calculate_peer_score([]))


class CalculateFinalScoreTests(SimpleTestCase):
    def test_uses_team_40_peer_60(self):
        self.assertEqual(
            calculate_final_score(Decimal("85.000000"), Decimal("90.000000")),
            Decimal("88.000000"),
        )

    def test_is_na_when_team_score_is_na(self):
        self.assertIsNone(calculate_final_score(None, Decimal("90.00")))

    def test_is_na_when_peer_score_is_na(self):
        self.assertIsNone(calculate_final_score(Decimal("85.00"), None))

    def test_uses_team_30_peer_40_tutor_30_when_tutor_score_given(self):
        # 85*.3 + 90*.4 + 80*.3 = 25.5 + 36 + 24 = 85.5
        self.assertEqual(
            calculate_final_score(Decimal("85.00"), Decimal("90.00"), Decimal("80.00")),
            Decimal("85.500000"),
        )

    def test_is_na_when_team_score_is_na_even_with_tutor_score(self):
        self.assertIsNone(calculate_final_score(None, Decimal("90.00"), Decimal("80.00")))


class DetermineDataStatusTests(SimpleTestCase):
    def test_not_applicable_when_nothing_expected(self):
        self.assertEqual(determine_data_status(expected_count=0, valid_count=0), "NOT_APPLICABLE")

    def test_no_data_when_nothing_valid(self):
        self.assertEqual(determine_data_status(expected_count=3, valid_count=0), "NO_DATA")

    def test_partial_when_some_but_not_all_valid(self):
        self.assertEqual(determine_data_status(expected_count=3, valid_count=2), "PARTIAL")

    def test_complete_when_all_expected_are_valid(self):
        self.assertEqual(determine_data_status(expected_count=3, valid_count=3), "COMPLETE")


class CalculateCoverageTests(SimpleTestCase):
    def test_is_none_when_nothing_expected(self):
        self.assertIsNone(calculate_coverage(expected_count=0, valid_count=0))

    def test_ratio_of_valid_to_expected(self):
        self.assertEqual(calculate_coverage(expected_count=10, valid_count=7), Decimal("0.700000"))


class CompetitionRankTests(SimpleTestCase):
    def test_no_ties_ranks_in_order(self):
        self.assertEqual(competition_rank([90, 80, 70]), [1, 2, 3])

    def test_tie_at_top_shares_rank_and_skips_next(self):
        self.assertEqual(competition_rank([90, 90, 85]), [1, 1, 3])

    def test_tie_in_middle_matches_refined_requirements_example(self):
        # RES-006 example: 1,2,2,4
        self.assertEqual(competition_rank([100, 90, 90, 80]), [1, 2, 2, 4])

    def test_all_tied_share_first_place(self):
        self.assertEqual(competition_rank([70, 70, 70]), [1, 1, 1])


class CalculateSeedTests(SimpleTestCase):
    def test_three_rounds_use_20_30_50(self):
        # 1회차=60, 2회차=80, 3회차=100 -> 60*.2 + 80*.3 + 100*.5 = 86
        self.assertEqual(
            calculate_seed([Decimal("60.00"), Decimal("80.00"), Decimal("100.00")]),
            Decimal("86.000000"),
        )

    def test_two_rounds_renormalize_from_the_back(self):
        # docs/REFINED-REQUIREMENTS.md AC-10: 과거 4.0, 최신 5.0 ->
        # (4.0*30 + 5.0*50) / 80 = 4.625
        self.assertEqual(calculate_seed([Decimal("4.0"), Decimal("5.0")]), Decimal("4.625000"))

    def test_single_round_gets_full_weight(self):
        self.assertEqual(calculate_seed([Decimal("60.00")]), Decimal("60.000000"))

    def test_no_valid_history_is_na_not_zero(self):
        # TEAM-005 / RES-016: 무시드는 N/A, 0점 대체 금지
        self.assertIsNone(calculate_seed([]))


class RevealIfPublishedTests(SimpleTestCase):
    """RES-010: 팀 1위·전체 팀 순위·본인 최종점수·본인 개인 순위는 각각 독립적으로
    공개되므로, 이 게이트는 회차 단위 bool이 아니라 항목별 공개 시각을 받는다."""

    def test_hides_value_when_item_is_not_yet_published(self):
        self.assertIsNone(reveal_if_published(Decimal("74.00"), published_at=None))

    def test_shows_value_when_item_has_a_publish_timestamp(self):
        published_at = "2026-08-15T12:00:00Z"
        self.assertEqual(
            reveal_if_published(Decimal("74.00"), published_at=published_at), Decimal("74.00")
        )


class ComputeInputDigestTests(SimpleTestCase):
    def test_is_order_independent(self):
        forward = compute_input_digest([(1, "88.00"), (2, "92.00")])
        reversed_order = compute_input_digest([(2, "92.00"), (1, "88.00")])
        self.assertEqual(forward, reversed_order)

    def test_changes_when_a_value_changes(self):
        original = compute_input_digest([(1, "88.00")])
        changed = compute_input_digest([(1, "89.00")])
        self.assertNotEqual(original, changed)

    def test_is_a_64_character_hex_string(self):
        digest = compute_input_digest([(1, "88.00")])
        self.assertEqual(len(digest), 64)
        int(digest, 16)  # raises ValueError if not valid hex


class RoundingTests(SimpleTestCase):
    def test_round_to_raw_keeps_six_decimal_places(self):
        self.assertEqual(round_to_raw(Decimal("2.3456789")), Decimal("2.345679"))

    def test_round_to_display_uses_half_up_to_two_decimal_places(self):
        self.assertEqual(round_to_display(Decimal("74.005")), Decimal("74.01"))

from decimal import Decimal

from django.test import SimpleTestCase

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
from results.templatetags.results_extras import as_five_point, five_point_percent


class ScoreFromAnswersTests(SimpleTestCase):
    def test_matches_requirements_worked_example(self):
        # docs/REQUIREMENTS.md: 모든 저장 점수는 5점 척도를 유지한다.
        self.assertEqual(score_from_answers([5, 4, 4, 5, 4]), Decimal("4.400000"))

    def test_all_max_answers_gives_five(self):
        self.assertEqual(score_from_answers([5, 5, 5, 5, 5]), Decimal("5.000000"))

    def test_all_min_answers_gives_one_not_zero(self):
        self.assertEqual(score_from_answers([1, 1, 1, 1, 1]), Decimal("1.000000"))


class CalculateTeamScoreTests(SimpleTestCase):
    def test_averages_every_received_team_review(self):
        received = [
            [5, 4, 4, 5, 4],
            [5, 5, 4, 5, 4],
            [4, 4, 3, 4, 4],
            [4, 4, 4, 5, 4],
        ]  # 4.4, 4.6, 3.8, 4.2
        self.assertEqual(calculate_team_score(received), Decimal("4.250000"))

    def test_is_na_when_team_received_no_reviews(self):
        # RES-002 / SUB-006: N/A, not 0.00
        self.assertIsNone(calculate_team_score([]))


class CalculatePeerScoreTests(SimpleTestCase):
    def test_averages_every_received_peer_review(self):
        received = [[5, 4, 5, 4], [4, 4, 4, 4, 4], [5, 5, 5, 5, 5]]
        self.assertEqual(calculate_peer_score(received), Decimal("4.500000"))

    def test_is_na_when_student_received_no_reviews(self):
        # RES-003 / SUB-006: N/A, not 0.00
        self.assertIsNone(calculate_peer_score([]))


class CalculateFinalScoreTests(SimpleTestCase):
    def test_uses_team_40_peer_60(self):
        self.assertEqual(
            calculate_final_score(Decimal("4.250000"), Decimal("4.500000")),
            Decimal("4.400000"),
        )

    def test_is_na_when_team_score_is_na(self):
        self.assertIsNone(calculate_final_score(None, Decimal("4.50")))

    def test_is_na_when_peer_score_is_na(self):
        self.assertIsNone(calculate_final_score(Decimal("4.25"), None))

    def test_uses_team_30_peer_40_tutor_30_when_tutor_score_given(self):
        # 4.25*.3 + 4.5*.4 + 4.0*.3 = 4.275
        self.assertEqual(
            calculate_final_score(Decimal("4.25"), Decimal("4.50"), Decimal("4.00")),
            Decimal("4.275000"),
        )

    def test_is_na_when_team_score_is_na_even_with_tutor_score(self):
        self.assertIsNone(calculate_final_score(None, Decimal("4.50"), Decimal("4.00")))


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
        self.assertEqual(
            competition_rank([Decimal("4.5"), Decimal("4.0"), Decimal("3.5")]), [1, 2, 3]
        )

    def test_tie_at_top_shares_rank_and_skips_next(self):
        self.assertEqual(
            competition_rank([Decimal("4.5"), Decimal("4.5"), Decimal("4.25")]), [1, 1, 3]
        )

    def test_tie_in_middle_matches_refined_requirements_example(self):
        # RES-006 example: 1,2,2,4
        self.assertEqual(
            competition_rank([Decimal("5.0"), Decimal("4.5"), Decimal("4.5"), Decimal("4.0")]),
            [1, 2, 2, 4],
        )

    def test_all_tied_share_first_place(self):
        self.assertEqual(competition_rank([Decimal("3.5")] * 3), [1, 1, 1])


class CalculateSeedTests(SimpleTestCase):
    def test_three_rounds_use_20_30_50(self):
        # 1회차=3, 2회차=4, 3회차=5 -> 3*.2 + 4*.3 + 5*.5 = 4.3
        self.assertEqual(
            calculate_seed([Decimal("3.00"), Decimal("4.00"), Decimal("5.00")]),
            Decimal("4.300000"),
        )

    def test_two_rounds_renormalize_from_the_back(self):
        # docs/REFINED-REQUIREMENTS.md AC-10: 과거 4.0, 최신 5.0 ->
        # (4.0*30 + 5.0*50) / 80 = 4.625
        self.assertEqual(calculate_seed([Decimal("4.0"), Decimal("5.0")]), Decimal("4.625000"))

    def test_single_round_gets_full_weight(self):
        self.assertEqual(calculate_seed([Decimal("3.00")]), Decimal("3.000000"))

    def test_no_valid_history_is_na_not_zero(self):
        # TEAM-005 / RES-016: 무시드는 N/A, 0점 대체 금지
        self.assertIsNone(calculate_seed([]))


class RevealIfPublishedTests(SimpleTestCase):
    """RES-010: 팀 1위·전체 팀 순위·본인 최종점수·본인 개인 순위는 각각 독립적으로
    공개되므로, 이 게이트는 회차 단위 bool이 아니라 항목별 공개 시각을 받는다."""

    def test_hides_value_when_item_is_not_yet_published(self):
        self.assertIsNone(reveal_if_published(Decimal("3.70"), published_at=None))

    def test_shows_value_when_item_has_a_publish_timestamp(self):
        published_at = "2026-08-15T12:00:00Z"
        self.assertEqual(
            reveal_if_published(Decimal("3.70"), published_at=published_at), Decimal("3.70")
        )


class ComputeInputDigestTests(SimpleTestCase):
    def test_is_order_independent(self):
        forward = compute_input_digest([(1, "4.40"), (2, "4.60")])
        reversed_order = compute_input_digest([(2, "4.60"), (1, "4.40")])
        self.assertEqual(forward, reversed_order)

    def test_changes_when_a_value_changes(self):
        original = compute_input_digest([(1, "4.40")])
        changed = compute_input_digest([(1, "4.45")])
        self.assertNotEqual(original, changed)

    def test_is_a_64_character_hex_string(self):
        digest = compute_input_digest([(1, "4.40")])
        self.assertEqual(len(digest), 64)
        int(digest, 16)  # raises ValueError if not valid hex


class RoundingTests(SimpleTestCase):
    def test_round_to_raw_keeps_six_decimal_places(self):
        self.assertEqual(round_to_raw(Decimal("2.3456789")), Decimal("2.345679"))

    def test_round_to_display_uses_half_up_to_two_decimal_places(self):
        self.assertEqual(round_to_display(Decimal("4.425")), Decimal("4.43"))


class ScoreDisplayFilterTests(SimpleTestCase):
    def test_truncates_to_two_decimal_places_without_rounding(self):
        self.assertEqual(as_five_point(Decimal("4.666667")), Decimal("4.66"))

    def test_keeps_two_decimal_places_for_whole_score(self):
        self.assertEqual(as_five_point(Decimal("4")), Decimal("4.00"))

    def test_preserves_missing_score(self):
        self.assertIsNone(as_five_point(None))


class FivePointPercentTests(SimpleTestCase):
    """점수 막대는 1~5점 값을 0~100% 너비로 환산한다 (5점 = 100%)."""

    def test_full_score_fills_the_bar(self):
        self.assertEqual(five_point_percent(Decimal("5.00")), 100)

    def test_scales_score_to_bar_width(self):
        self.assertEqual(five_point_percent(Decimal("4.500000")), 90)

    def test_preserves_missing_score(self):
        self.assertIsNone(five_point_percent(None))

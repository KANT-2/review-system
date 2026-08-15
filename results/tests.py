from decimal import Decimal

from django.test import SimpleTestCase

from results.services import (
    calculate_final_score,
    calculate_peer_score,
    calculate_seed,
    calculate_team_score,
    competition_rank,
    reveal_if_published,
    round_to_1dp,
    round_to_2dp,
    score_from_answers,
)


class ScoreFromAnswersTests(SimpleTestCase):
    def test_matches_requirements_worked_example(self):
        # docs/REQUIREMENTS.md 예시: [5,4,4,5,4] -> 평균 4.4 -> 88점
        self.assertEqual(score_from_answers([5, 4, 4, 5, 4]), Decimal("88.00"))

    def test_all_max_answers_gives_100(self):
        self.assertEqual(score_from_answers([5, 5, 5, 5, 5]), Decimal("100.00"))

    def test_all_min_answers_gives_20_not_zero(self):
        self.assertEqual(score_from_answers([1, 1, 1, 1, 1]), Decimal("20.00"))


class CalculateTeamScoreTests(SimpleTestCase):
    def test_averages_every_received_team_review(self):
        received = [
            [5, 4, 4, 5, 4],
            [5, 5, 4, 5, 4],
            [4, 4, 3, 4, 4],
            [4, 4, 4, 5, 4],
        ]  # 88,92,76,84
        self.assertEqual(calculate_team_score(received), Decimal("85.00"))

    def test_is_zero_when_team_received_no_reviews(self):
        self.assertEqual(calculate_team_score([]), Decimal("0.00"))


class CalculatePeerScoreTests(SimpleTestCase):
    def test_averages_every_received_peer_review(self):
        received = [[5, 4, 5, 4], [4, 4, 4, 4, 4], [5, 5, 5, 5, 5]]  # 90, 80, 100
        self.assertEqual(calculate_peer_score(received), Decimal("90.00"))

    def test_is_zero_when_student_received_no_reviews(self):
        self.assertEqual(calculate_peer_score([]), Decimal("0.00"))


class CalculateFinalScoreTests(SimpleTestCase):
    def test_uses_team_40_peer_60(self):
        self.assertEqual(
            calculate_final_score(Decimal("85.00"), Decimal("90.00")), Decimal("88.00")
        )


class CompetitionRankTests(SimpleTestCase):
    def test_no_ties_ranks_in_order(self):
        self.assertEqual(competition_rank([90, 80, 70]), [1, 2, 3])

    def test_tied_values_share_rank_and_skip_next(self):
        self.assertEqual(competition_rank([90, 90, 85]), [1, 1, 3])

    def test_all_tied_share_first_place(self):
        self.assertEqual(competition_rank([70, 70, 70]), [1, 1, 1])


class CalculateSeedTests(SimpleTestCase):
    def test_three_rounds_use_20_30_50(self):
        # 1회차=0, 2회차=80, 3회차=100 -> 0*.2 + 80*.3 + 100*.5 = 74
        self.assertEqual(
            calculate_seed([Decimal("0.00"), Decimal("80.00"), Decimal("100.00")]),
            Decimal("74.00"),
        )

    def test_two_rounds_renormalize_from_the_front(self):
        # 1회차=80, 2회차=90 -> 20/(20+30), 30/(20+30) 재정규화 -> 86 (30/50, 50/... 아님)
        self.assertEqual(calculate_seed([Decimal("80.00"), Decimal("90.00")]), Decimal("86.00"))

    def test_single_round_gets_full_weight(self):
        self.assertEqual(calculate_seed([Decimal("60.00")]), Decimal("60.00"))

    def test_no_rounds_gives_zero(self):
        self.assertEqual(calculate_seed([]), Decimal("0.00"))


class RevealIfPublishedTests(SimpleTestCase):
    def test_hides_value_when_round_is_unpublished(self):
        self.assertIsNone(reveal_if_published(Decimal("74.00"), round_is_published=False))

    def test_shows_value_when_round_is_published(self):
        self.assertEqual(
            reveal_if_published(Decimal("74.00"), round_is_published=True), Decimal("74.00")
        )


class RoundingTests(SimpleTestCase):
    def test_round_to_2dp_uses_half_up(self):
        self.assertEqual(round_to_2dp(Decimal("2.345")), Decimal("2.35"))

    def test_round_to_1dp_uses_half_up(self):
        self.assertEqual(round_to_1dp(Decimal("74.05")), Decimal("74.1"))

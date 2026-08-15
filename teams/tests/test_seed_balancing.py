from decimal import Decimal
from unittest import TestCase

from teams.services import calculate_seed_metrics


class CalculateSeedMetricsTests(TestCase):
    def test_calculates_team_averages_and_population_standard_deviation(self):
        teams = [[1, 2], [3, 4]]
        seed_scores = {
            1: Decimal("100"),
            2: Decimal("80"),
            3: Decimal("60"),
            4: Decimal("40"),
        }

        metrics = calculate_seed_metrics(teams, seed_scores)

        self.assertEqual(
            metrics.team_averages,
            [Decimal("90"), Decimal("50")],
        )
        self.assertEqual(metrics.population_standard_deviation, Decimal("20"))
        self.assertEqual(metrics.seeded_participant_count, 4)

    def test_ignores_participants_without_valid_seed_scores(self):
        teams = [[1, 2], [3, 4]]
        seed_scores = {
            1: Decimal("80"),
            2: None,
            3: None,
        }

        metrics = calculate_seed_metrics(teams, seed_scores)

        self.assertEqual(metrics.team_averages, [Decimal("80"), None])
        self.assertIsNone(metrics.population_standard_deviation)
        self.assertEqual(metrics.seeded_participant_count, 1)

    def test_returns_na_when_all_participants_have_no_seed_scores(self):
        teams = [[1, 2], [3, 4]]
        seed_scores = {
            1: None,
            2: None,
            3: None,
            4: None,
        }

        metrics = calculate_seed_metrics(teams, seed_scores)

        self.assertEqual(metrics.team_averages, [None, None])
        self.assertIsNone(metrics.population_standard_deviation)
        self.assertEqual(metrics.seeded_participant_count, 0)

    def test_uses_decimal_precision_without_display_rounding(self):
        teams = [[1, 2], [3]]
        seed_scores = {
            1: Decimal("1"),
            2: Decimal("2"),
            3: Decimal("2"),
        }

        metrics = calculate_seed_metrics(teams, seed_scores)

        self.assertEqual(
            metrics.team_averages,
            [Decimal("1.5"), Decimal("2")],
        )
        self.assertEqual(
            metrics.population_standard_deviation,
            Decimal("0.25"),
        )

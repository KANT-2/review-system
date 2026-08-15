import random
from decimal import Decimal
from unittest import TestCase

from teams.services import calculate_seed_metrics, create_seed_balanced_assignment


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


class CreateSeedBalancedAssignmentTests(TestCase):
    def setUp(self):
        self.participant_ids = list(range(1, 11))
        self.seed_scores = {
            1: Decimal("100"),
            2: Decimal("90"),
            3: Decimal("80"),
            4: Decimal("70"),
            5: Decimal("30"),
            6: Decimal("20"),
            7: Decimal("10"),
            8: Decimal("0"),
            9: None,
        }

    def test_assigns_every_participant_once_with_balanced_team_sizes(self):
        assignment = create_seed_balanced_assignment(
            self.participant_ids,
            self.seed_scores,
            3,
            rng=random.Random(7),
        )

        assigned_ids = [participant_id for team in assignment.teams for participant_id in team]
        team_sizes = [len(team) for team in assignment.teams]

        self.assertCountEqual(assigned_ids, self.participant_ids)
        self.assertEqual(len(assigned_ids), len(set(assigned_ids)))
        self.assertLessEqual(max(team_sizes) - min(team_sizes), 1)

    def test_does_not_worsen_seed_population_standard_deviation(self):
        assignment = create_seed_balanced_assignment(
            self.participant_ids,
            self.seed_scores,
            3,
            rng=random.Random(7),
        )

        self.assertIsNotNone(assignment.initial_metrics.population_standard_deviation)
        self.assertIsNotNone(assignment.final_metrics.population_standard_deviation)
        self.assertLessEqual(
            assignment.final_metrics.population_standard_deviation,
            assignment.initial_metrics.population_standard_deviation,
        )
        self.assertLessEqual(assignment.optimization_count, 100)

    def test_all_seedless_participants_still_receive_balanced_teams(self):
        assignment = create_seed_balanced_assignment(
            self.participant_ids,
            {},
            3,
            rng=random.Random(7),
        )

        team_sizes = [len(team) for team in assignment.teams]
        self.assertLessEqual(max(team_sizes) - min(team_sizes), 1)
        self.assertIsNone(assignment.final_metrics.population_standard_deviation)
        self.assertEqual(assignment.final_metrics.seeded_participant_count, 0)
        self.assertEqual(assignment.optimization_count, 0)

    def test_skips_optimization_when_fewer_than_two_teams_have_seed_averages(self):
        assignment = create_seed_balanced_assignment(
            self.participant_ids,
            {1: Decimal("50")},
            3,
            rng=random.Random(7),
        )

        self.assertIsNone(assignment.initial_metrics.population_standard_deviation)
        self.assertEqual(assignment.optimization_count, 0)

    def test_does_not_modify_original_inputs(self):
        participant_ids = self.participant_ids.copy()
        seed_scores = self.seed_scores.copy()

        create_seed_balanced_assignment(
            participant_ids,
            seed_scores,
            3,
            rng=random.Random(7),
        )

        self.assertEqual(participant_ids, self.participant_ids)
        self.assertEqual(seed_scores, self.seed_scores)

    def test_rejects_more_than_one_hundred_optimizations(self):
        with self.assertRaisesRegex(
            ValueError,
            "max_optimizations must be between 0 and 100",
        ):
            create_seed_balanced_assignment(
                self.participant_ids,
                self.seed_scores,
                3,
                max_optimizations=101,
            )

import random
from decimal import Decimal
from unittest import TestCase

from teams.application import create_auto_team_board
from teams.services import AssignmentValidationError


class CreateAutoTeamBoardTests(TestCase):
    def setUp(self):
        self.participant_ids = [101, 102, 103, 104, 105, 106, 107]
        self.seed_scores = {
            101: Decimal("90"),
            102: Decimal("80"),
            103: Decimal("70"),
            104: Decimal("40"),
            105: Decimal("30"),
            106: None,
        }

    def test_creates_numbered_editable_teams_for_requested_team_count(self):
        result = create_auto_team_board(
            round_id=10,
            lock_version=4,
            participant_ids=self.participant_ids,
            seed_scores=self.seed_scores,
            team_count=3,
            rng=random.Random(7),
        )

        self.assertEqual(result.board.round_id, 10)
        self.assertEqual(result.board.lock_version, 4)
        self.assertEqual(
            [team.team_number for team in result.board.teams],
            [1, 2, 3],
        )
        self.assertEqual(
            [team.name for team in result.board.teams],
            ["1팀", "2팀", "3팀"],
        )

    def test_assigns_all_participants_once_with_balanced_sizes(self):
        result = create_auto_team_board(
            round_id=10,
            lock_version=4,
            participant_ids=self.participant_ids,
            seed_scores=self.seed_scores,
            team_count=3,
            rng=random.Random(7),
        )

        assigned_ids = [
            participant_id for team in result.board.teams for participant_id in team.participant_ids
        ]
        team_sizes = [len(team.participant_ids) for team in result.board.teams]
        self.assertCountEqual(assigned_ids, self.participant_ids)
        self.assertEqual(len(assigned_ids), len(set(assigned_ids)))
        self.assertLessEqual(max(team_sizes) - min(team_sizes), 1)

    def test_exposes_quality_information_for_the_screen(self):
        result = create_auto_team_board(
            round_id=10,
            lock_version=4,
            participant_ids=self.participant_ids,
            seed_scores=self.seed_scores,
            team_count=3,
            previous_teammate_pairs={(101, 102), (103, 104)},
            rng=random.Random(7),
        )

        self.assertEqual(result.seeded_participant_count, 5)
        self.assertIsNotNone(result.initial_standard_deviation)
        self.assertIsNotNone(result.final_standard_deviation)
        self.assertLessEqual(
            result.final_standard_deviation,
            result.initial_standard_deviation,
        )
        self.assertLessEqual(
            result.final_repeated_pair_count,
            result.initial_repeated_pair_count,
        )
        self.assertLessEqual(result.optimization_count, 100)

    def test_rejects_team_count_below_two_without_creating_board(self):
        # AssignmentValidationError는 ValueError의 하위형이다 - 뷰가 500 대신 400으로 돌려준다.
        with self.assertRaisesRegex(AssignmentValidationError, "팀은 2개 이상"):
            create_auto_team_board(
                round_id=10,
                lock_version=4,
                participant_ids=self.participant_ids,
                seed_scores=self.seed_scores,
                team_count=1,
            )

    def test_rejects_team_count_above_participant_count(self):
        with self.assertRaisesRegex(AssignmentValidationError, "7명뿐이라 8개 팀으로"):
            create_auto_team_board(
                round_id=10,
                lock_version=4,
                participant_ids=self.participant_ids,
                seed_scores=self.seed_scores,
                team_count=8,
            )

    def test_same_random_seed_reproduces_same_board(self):
        first_result = create_auto_team_board(
            round_id=10,
            lock_version=4,
            participant_ids=self.participant_ids,
            seed_scores=self.seed_scores,
            team_count=3,
            rng=random.Random(13),
        )
        second_result = create_auto_team_board(
            round_id=10,
            lock_version=4,
            participant_ids=self.participant_ids,
            seed_scores=self.seed_scores,
            team_count=3,
            rng=random.Random(13),
        )

        self.assertEqual(first_result, second_result)

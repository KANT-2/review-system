import random
from unittest import TestCase

from teams.services import distribute_participants


class DistributeParticipantsTests(TestCase):
    def test_assigns_every_participant_exactly_once(self):
        participant_ids = [1, 2, 3, 4, 5, 6]

        teams = distribute_participants(
            participant_ids,
            team_count=2,
            rng=random.Random(1),
        )

        assigned_participant_ids = [participant_id for team in teams for participant_id in team]

        self.assertCountEqual(assigned_participant_ids, participant_ids)
        self.assertEqual(
            len(assigned_participant_ids),
            len(set(assigned_participant_ids)),
        )

    def test_keeps_team_size_difference_at_most_one(self):
        participant_ids = list(range(1, 11))

        teams = distribute_participants(
            participant_ids,
            team_count=3,
            rng=random.Random(1),
        )

        team_sizes = [len(team) for team in teams]

        self.assertLessEqual(max(team_sizes) - min(team_sizes), 1)

    def test_allows_one_participant_per_team(self):
        participant_ids = [1, 2, 3]

        teams = distribute_participants(
            participant_ids,
            team_count=3,
            rng=random.Random(1),
        )

        self.assertEqual([len(team) for team in teams], [1, 1, 1])

    def test_rejects_team_count_less_than_two(self):
        with self.assertRaises(ValueError):
            distribute_participants(
                [1, 2, 3],
                team_count=1,
                rng=random.Random(1),
            )

    def test_rejects_team_count_greater_than_participant_count(self):
        with self.assertRaises(ValueError):
            distribute_participants(
                [1, 2],
                team_count=3,
                rng=random.Random(1),
            )

    def test_rejects_duplicate_participant_ids(self):
        with self.assertRaises(ValueError):
            distribute_participants(
                [1, 1, 2],
                team_count=2,
                rng=random.Random(1),
            )

    def test_does_not_modify_original_participant_list(self):
        participant_ids = [1, 2, 3, 4]
        original_participant_ids = participant_ids.copy()

        distribute_participants(
            participant_ids,
            team_count=2,
            rng=random.Random(1),
        )

        self.assertEqual(participant_ids, original_participant_ids)

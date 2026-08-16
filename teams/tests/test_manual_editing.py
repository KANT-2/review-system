from unittest import TestCase

from teams.domain import (
    TeamBoard,
    TeamDraft,
    TeamEditingError,
    move_participant,
    swap_participants,
)


class ManualTeamEditingTests(TestCase):
    def setUp(self):
        self.board = TeamBoard(
            round_id=1,
            lock_version=3,
            teams=(
                TeamDraft(1, "1팀", (101, 102)),
                TeamDraft(2, "2팀", (103, 104)),
                TeamDraft(3, "3팀", (105, 106)),
            ),
        )

    def test_moves_participant_to_another_team(self):
        updated_board = move_participant(self.board, 102, 2)

        self.assertEqual(updated_board.teams[0].participant_ids, (101,))
        self.assertEqual(updated_board.teams[1].participant_ids, (103, 104, 102))
        self.assertEqual(updated_board.lock_version, 3)

    def test_move_does_not_modify_original_board(self):
        move_participant(self.board, 102, 2)

        self.assertEqual(self.board.teams[0].participant_ids, (101, 102))
        self.assertEqual(self.board.teams[1].participant_ids, (103, 104))

    def test_move_to_current_team_returns_same_board(self):
        updated_board = move_participant(self.board, 101, 1)

        self.assertIs(updated_board, self.board)

    def test_swaps_participants_between_teams(self):
        updated_board = swap_participants(self.board, 101, 104)

        self.assertEqual(updated_board.teams[0].participant_ids, (104, 102))
        self.assertEqual(updated_board.teams[1].participant_ids, (103, 101))
        self.assertEqual(updated_board.teams[2], self.board.teams[2])

    def test_swap_keeps_team_sizes(self):
        updated_board = swap_participants(self.board, 101, 104)

        self.assertEqual(
            [len(team.participant_ids) for team in updated_board.teams],
            [2, 2, 2],
        )

    def test_rejects_move_to_unknown_team(self):
        with self.assertRaisesRegex(TeamEditingError, "team does not exist: 4"):
            move_participant(self.board, 101, 4)

    def test_rejects_unknown_participant(self):
        with self.assertRaisesRegex(
            TeamEditingError,
            "participant is not assigned: 999",
        ):
            move_participant(self.board, 999, 2)

    def test_rejects_swap_inside_same_team(self):
        with self.assertRaisesRegex(
            TeamEditingError,
            "participants must belong to different teams",
        ):
            swap_participants(self.board, 101, 102)

    def test_rejects_same_participant_swap(self):
        with self.assertRaisesRegex(
            TeamEditingError,
            "two different participants are required",
        ):
            swap_participants(self.board, 101, 101)

    def test_rejects_ambiguous_duplicate_assignment(self):
        invalid_board = TeamBoard(
            round_id=1,
            lock_version=3,
            teams=(
                TeamDraft(1, "1팀", (101, 102)),
                TeamDraft(2, "2팀", (101, 103)),
            ),
        )

        with self.assertRaisesRegex(
            TeamEditingError,
            "participant is assigned more than once: 101",
        ):
            move_participant(invalid_board, 101, 2)

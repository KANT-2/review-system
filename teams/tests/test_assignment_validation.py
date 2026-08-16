from unittest import TestCase

from teams.services import (
    AssignmentValidationError,
    ImbalanceConfirmationRequired,
    validate_assignment,
)


class ValidateAssignmentTests(TestCase):
    def setUp(self):
        self.participant_ids = [1, 2, 3, 4, 5, 6]

    def test_accepts_complete_balanced_assignment(self):
        result = validate_assignment(
            [[1, 2], [3, 4], [5, 6]],
            self.participant_ids,
        )

        self.assertEqual(result.team_count, 3)
        self.assertEqual(result.participant_count, 6)
        self.assertEqual(result.team_sizes, [2, 2, 2])
        self.assertFalse(result.has_size_imbalance)

    def test_rejects_fewer_than_two_teams(self):
        with self.assertRaisesRegex(
            AssignmentValidationError,
            "at least two teams are required",
        ):
            validate_assignment([[1, 2, 3, 4, 5, 6]], self.participant_ids)

    def test_rejects_empty_team(self):
        with self.assertRaisesRegex(
            AssignmentValidationError,
            "empty teams are not allowed",
        ):
            validate_assignment([[1, 2, 3], [], [4, 5, 6]], self.participant_ids)

    def test_rejects_duplicate_participant(self):
        with self.assertRaisesRegex(
            AssignmentValidationError,
            r"duplicate participants are not allowed: \[2\]",
        ):
            validate_assignment([[1, 2], [2, 3], [4, 5, 6]], self.participant_ids)

    def test_rejects_missing_participant(self):
        with self.assertRaisesRegex(
            AssignmentValidationError,
            r"participants are missing: \[6\]",
        ):
            validate_assignment([[1, 2], [3, 4], [5]], self.participant_ids)

    def test_rejects_participant_outside_current_round(self):
        with self.assertRaisesRegex(
            AssignmentValidationError,
            r"unexpected participants were assigned: \[7\]",
        ):
            validate_assignment([[1, 2], [3, 4], [5, 6, 7]], self.participant_ids)

    def test_requires_confirmation_for_large_manual_imbalance(self):
        with self.assertRaisesRegex(
            ImbalanceConfirmationRequired,
            "team size imbalance requires explicit confirmation",
        ):
            validate_assignment([[1, 2, 3, 4], [5, 6]], self.participant_ids)

    def test_accepts_large_manual_imbalance_after_confirmation(self):
        result = validate_assignment(
            [[1, 2, 3, 4], [5, 6]],
            self.participant_ids,
            imbalance_confirmed=True,
        )

        self.assertTrue(result.has_size_imbalance)
        self.assertEqual(result.team_sizes, [4, 2])

    def test_rejects_duplicate_expected_participant_ids(self):
        with self.assertRaisesRegex(
            ValueError,
            "expected_participant_ids must not contain duplicates",
        ):
            validate_assignment([[1, 2], [3, 4]], [1, 2, 3, 4, 4])

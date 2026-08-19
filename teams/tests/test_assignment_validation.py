from unittest import TestCase

from teams.services import (
    AssignmentValidationError,
    ImbalanceConfirmationRequired,
    UnassignedParticipantsConfirmationRequired,
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

    def test_requires_confirmation_for_unassigned_participant(self):
        # 아직 다 못 배정한 채로 저장하려면 먼저 재확인이 필요하다 - 편성 중간에도
        # 저장할 수 있어야 하지만, 실수로 빠뜨린 걸 그냥 넘어가서는 안 된다.
        with self.assertRaisesRegex(
            UnassignedParticipantsConfirmationRequired,
            r"participants are not yet assigned to any team: \[6\]",
        ):
            validate_assignment([[1, 2], [3, 4], [5]], self.participant_ids)

    def test_accepts_unassigned_participant_after_confirmation(self):
        # 재확인만 하면 일부 미배정 상태로도 저장할 수 있다 - 회차 시작은 별도로
        # 전원 배정을 강제하므로(rounds.services.round_start_errors) 안전하다.
        result = validate_assignment(
            [[1, 2], [3, 4], [5]],
            self.participant_ids,
            unassigned_confirmed=True,
        )

        self.assertEqual(result.participant_count, 5)
        self.assertEqual(result.team_sizes, [2, 2, 1])

    def test_participant_outside_current_round_is_never_confirmable(self):
        # 회차에 속하지 않는 참가자가 섞여 온 건 실수로 넘어갈 수 있는 확인 대상이
        # 아니라 데이터가 어긋난 것이다 - unassigned_confirmed를 켜도 막힌다.
        with self.assertRaisesRegex(
            AssignmentValidationError,
            r"unexpected participants were assigned: \[7\]",
        ):
            validate_assignment(
                [[1, 2], [3, 4], [5, 6, 7]],
                self.participant_ids,
                unassigned_confirmed=True,
            )

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

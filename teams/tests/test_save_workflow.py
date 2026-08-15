from copy import deepcopy
from unittest import TestCase

from teams.application import (
    RoundForTeamEditing,
    RoundNotEditableError,
    TeamVersionConflictError,
    save_team_configuration,
)
from teams.domain import TeamBoard, TeamDraft
from teams.services import AssignmentValidationError, ImbalanceConfirmationRequired


class FakeTeamSaveUnitOfWork:
    def __init__(self, current_round, saved_board=None, *, fail_audit=False):
        self.current_round = current_round
        self.saved_board = saved_board
        self.audit_records = []
        self.fail_audit = fail_audit
        self.committed = False

    def __enter__(self):
        self._original_state = deepcopy((self.current_round, self.saved_board, self.audit_records))
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None or not self.committed:
            self.current_round, self.saved_board, self.audit_records = self._original_state

    def get_round_for_update(self, round_id):
        if self.current_round.round_id != round_id:
            raise LookupError(f"round does not exist: {round_id}")
        return self.current_round

    def replace_team_configuration(self, board):
        self.saved_board = board

    def increase_lock_version(self, round_id):
        self.current_round = RoundForTeamEditing(
            round_id=self.current_round.round_id,
            status=self.current_round.status,
            lock_version=self.current_round.lock_version + 1,
            participant_ids=self.current_round.participant_ids,
        )

    def record_team_configuration_saved(self, round_id, actor_id):
        if self.fail_audit:
            raise RuntimeError("audit storage failed")
        self.audit_records.append((round_id, actor_id))

    def commit(self):
        self.committed = True


class SaveTeamConfigurationTests(TestCase):
    def setUp(self):
        self.current_round = RoundForTeamEditing(
            round_id=1,
            status="DRAFT",
            lock_version=3,
            participant_ids=(101, 102, 103, 104, 105, 106),
        )
        self.original_board = TeamBoard(
            round_id=1,
            lock_version=3,
            teams=(
                TeamDraft(1, "1팀", (101, 102)),
                TeamDraft(2, "2팀", (103, 104)),
                TeamDraft(3, "3팀", (105, 106)),
            ),
        )

    def test_saves_complete_configuration_and_increases_version(self):
        unit_of_work = FakeTeamSaveUnitOfWork(self.current_round)

        saved_board = save_team_configuration(
            self.original_board,
            unit_of_work,
            actor_id=900,
        )

        self.assertEqual(unit_of_work.saved_board, self.original_board)
        self.assertEqual(unit_of_work.current_round.lock_version, 4)
        self.assertEqual(unit_of_work.audit_records, [(1, 900)])
        self.assertTrue(unit_of_work.committed)
        self.assertEqual(saved_board.lock_version, 4)

    def test_rejects_stale_version_without_changing_saved_configuration(self):
        current_round = RoundForTeamEditing(
            round_id=1,
            status="DRAFT",
            lock_version=4,
            participant_ids=self.current_round.participant_ids,
        )
        unit_of_work = FakeTeamSaveUnitOfWork(current_round, self.original_board)
        stale_board = TeamBoard(
            round_id=1,
            lock_version=3,
            teams=self.original_board.teams,
        )

        with self.assertRaisesRegex(TeamVersionConflictError, "reload the latest"):
            save_team_configuration(stale_board, unit_of_work, actor_id=900)

        self.assertEqual(unit_of_work.saved_board, self.original_board)
        self.assertEqual(unit_of_work.current_round.lock_version, 4)
        self.assertEqual(unit_of_work.audit_records, [])

    def test_rejects_started_round(self):
        current_round = RoundForTeamEditing(
            round_id=1,
            status="IN_PROGRESS",
            lock_version=3,
            participant_ids=self.current_round.participant_ids,
        )
        unit_of_work = FakeTeamSaveUnitOfWork(current_round)

        with self.assertRaisesRegex(RoundNotEditableError, "only DRAFT"):
            save_team_configuration(self.original_board, unit_of_work, actor_id=900)

        self.assertIsNone(unit_of_work.saved_board)

    def test_rejects_completed_round(self):
        current_round = RoundForTeamEditing(
            round_id=1,
            status="COMPLETED",
            lock_version=3,
            participant_ids=self.current_round.participant_ids,
        )
        unit_of_work = FakeTeamSaveUnitOfWork(current_round)

        with self.assertRaises(RoundNotEditableError):
            save_team_configuration(self.original_board, unit_of_work, actor_id=900)

    def test_rejects_missing_participant(self):
        unit_of_work = FakeTeamSaveUnitOfWork(self.current_round)
        invalid_board = TeamBoard(
            round_id=1,
            lock_version=3,
            teams=(
                TeamDraft(1, "1팀", (101, 102)),
                TeamDraft(2, "2팀", (103, 104)),
                TeamDraft(3, "3팀", (105,)),
            ),
        )

        with self.assertRaisesRegex(AssignmentValidationError, r"missing: \[106\]"):
            save_team_configuration(invalid_board, unit_of_work, actor_id=900)

        self.assertIsNone(unit_of_work.saved_board)

    def test_requires_confirmation_for_large_size_imbalance(self):
        unit_of_work = FakeTeamSaveUnitOfWork(self.current_round)
        imbalanced_board = TeamBoard(
            round_id=1,
            lock_version=3,
            teams=(
                TeamDraft(1, "1팀", (101, 102, 103, 104)),
                TeamDraft(2, "2팀", (105, 106)),
            ),
        )

        with self.assertRaises(ImbalanceConfirmationRequired):
            save_team_configuration(imbalanced_board, unit_of_work, actor_id=900)

        saved_board = save_team_configuration(
            imbalanced_board,
            unit_of_work,
            actor_id=900,
            imbalance_confirmed=True,
        )
        self.assertEqual(saved_board.lock_version, 4)

    def test_rolls_back_replacement_and_version_when_audit_fails(self):
        previous_board = TeamBoard(
            round_id=1,
            lock_version=3,
            teams=(
                TeamDraft(1, "기존 1팀", (101, 103)),
                TeamDraft(2, "기존 2팀", (102, 104)),
                TeamDraft(3, "기존 3팀", (105, 106)),
            ),
        )
        unit_of_work = FakeTeamSaveUnitOfWork(
            self.current_round,
            previous_board,
            fail_audit=True,
        )

        with self.assertRaisesRegex(RuntimeError, "audit storage failed"):
            save_team_configuration(self.original_board, unit_of_work, actor_id=900)

        self.assertEqual(unit_of_work.saved_board, previous_board)
        self.assertEqual(unit_of_work.current_round.lock_version, 3)
        self.assertEqual(unit_of_work.audit_records, [])

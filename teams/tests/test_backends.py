import random
from copy import deepcopy
from decimal import Decimal
from unittest import TestCase

from teams.application import (
    RoundForTeamEditing,
    RoundNotEditableError,
    TeamVersionConflictError,
)
from teams.backends import ServiceTeamsBackend
from teams.contracts import AutoAssignmentRequest, TeamSaveRequest
from teams.domain import TeamBoard, TeamDraft
from teams.queries import ParticipantSnapshot, StoredTeam, TeamQueryData


class FakeDataSource:
    def __init__(self):
        self.query_data = TeamQueryData(
            round_id=10,
            round_status="DRAFT",
            lock_version=4,
            participants=(
                ParticipantSnapshot(101, 1, "A001", "김민수"),
                ParticipantSnapshot(102, 2, "A002", "이영희"),
                ParticipantSnapshot(103, 3, "A003", "박지훈"),
                ParticipantSnapshot(104, 4, "A004", "최서연"),
            ),
            teams=(
                StoredTeam(1, "1팀", (101, 102)),
                StoredTeam(2, "2팀", (103, 104)),
            ),
        )
        self.current_round = RoundForTeamEditing(
            10,
            "DRAFT",
            4,
            (101, 102, 103, 104),
        )
        self.seed_calls = []
        self.previous_pair_calls = []

    def get_current_student_round_data(self, user_id):
        return self.query_data

    def get_round_team_data(self, round_id):
        return self.query_data

    def get_round_for_auto_assignment(self, round_id):
        return self.current_round

    def get_seed_scores(self, round_id, participant_ids):
        self.seed_calls.append((round_id, participant_ids))
        return {
            101: Decimal("90"),
            102: Decimal("70"),
            103: Decimal("30"),
            104: None,
        }

    def get_previous_teammate_pairs(self, round_id, participant_ids):
        self.previous_pair_calls.append((round_id, participant_ids))
        return {(101, 102)}


class FakeUnitOfWork:
    def __init__(self, current_round):
        self.current_round = current_round
        self.saved_board = None
        self.audit_records = []
        self.committed = False

    def __enter__(self):
        self.original_state = deepcopy((self.current_round, self.saved_board, self.audit_records))
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None or not self.committed:
            self.current_round, self.saved_board, self.audit_records = self.original_state

    def get_round_for_update(self, round_id):
        return self.current_round

    def replace_team_configuration(self, board):
        self.saved_board = board

    def increase_lock_version(self, round_id):
        self.current_round = RoundForTeamEditing(
            round_id,
            self.current_round.status,
            self.current_round.lock_version + 1,
            self.current_round.participant_ids,
        )

    def record_team_configuration_saved(self, round_id, actor_id):
        self.audit_records.append((round_id, actor_id))

    def commit(self):
        self.committed = True


class ServiceTeamsBackendTests(TestCase):
    def setUp(self):
        self.data_source = FakeDataSource()
        self.unit_of_work = FakeUnitOfWork(self.data_source.current_round)
        self.backend = ServiceTeamsBackend(
            self.data_source,
            lambda: self.unit_of_work,
            rng_factory=lambda: random.Random(7),
        )

    def test_builds_student_team_from_current_round_data(self):
        view = self.backend.get_student_team(user_id=1)

        self.assertEqual(view.team.team_number, 1)
        self.assertEqual(view.team.members[0].display_name, "김민수")

    def test_builds_management_team_from_round_data(self):
        view = self.backend.get_management_team(round_id=10)

        self.assertEqual(len(view.teams), 2)
        self.assertFalse(view.is_read_only)

    def test_collects_round_seed_and_previous_pair_data_for_auto_assignment(self):
        result = self.backend.create_auto_assignment(
            10,
            AutoAssignmentRequest(team_count=2, lock_version=4),
        )

        self.assertEqual(len(result.board.teams), 2)
        self.assertEqual(self.data_source.seed_calls, [(10, (101, 102, 103, 104))])
        self.assertEqual(
            self.data_source.previous_pair_calls,
            [(10, (101, 102, 103, 104))],
        )

    def test_rejects_auto_assignment_for_stale_version_before_seed_queries(self):
        with self.assertRaises(TeamVersionConflictError):
            self.backend.create_auto_assignment(
                10,
                AutoAssignmentRequest(team_count=2, lock_version=3),
            )

        self.assertEqual(self.data_source.seed_calls, [])

    def test_rejects_auto_assignment_after_round_starts(self):
        self.data_source.current_round = RoundForTeamEditing(
            10,
            "IN_PROGRESS",
            4,
            (101, 102, 103, 104),
        )

        with self.assertRaises(RoundNotEditableError):
            self.backend.create_auto_assignment(
                10,
                AutoAssignmentRequest(team_count=2, lock_version=4),
            )

    def test_saves_board_with_actor_audit_record(self):
        board = TeamBoard(
            10,
            4,
            (
                TeamDraft(1, "1팀", (101, 102)),
                TeamDraft(2, "2팀", (103, 104)),
            ),
        )
        request_data = TeamSaveRequest(board, imbalance_confirmed=False)

        saved_board = self.backend.save_team_configuration(10, 900, request_data)

        self.assertEqual(saved_board.lock_version, 5)
        self.assertEqual(self.unit_of_work.audit_records, [(10, 900)])

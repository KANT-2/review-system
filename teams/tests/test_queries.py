from unittest import TestCase

from teams.queries import (
    ParticipantSnapshot,
    RoundParticipantNotFoundError,
    StoredTeam,
    TeamQueryData,
    TeamQueryError,
    build_management_team_view,
    build_student_team_view,
)


class TeamQueryTests(TestCase):
    def setUp(self):
        self.data = TeamQueryData(
            round_id=1,
            round_status="DRAFT",
            lock_version=4,
            participants=(
                ParticipantSnapshot(101, 1, "A001", "김민수"),
                ParticipantSnapshot(102, 2, "A002", "이영희"),
                ParticipantSnapshot(103, 3, "A003", "박지훈"),
                ParticipantSnapshot(104, 4, "A004", "최서연"),
                ParticipantSnapshot(105, 5, "A005", "정현우"),
                ParticipantSnapshot(106, 6, "A006", "한지민"),
            ),
            teams=(
                StoredTeam(2, "2팀", (103, 104)),
                StoredTeam(1, "1팀", (101, 102)),
                StoredTeam(3, "3팀", (105,)),
            ),
        )

    def test_management_view_returns_sorted_teams_and_unassigned_members(self):
        view = build_management_team_view(self.data)

        self.assertEqual([team.team_number for team in view.teams], [1, 2, 3])
        self.assertEqual(view.teams[0].members[0].display_name, "김민수")
        self.assertEqual(
            [member.participant_id for member in view.unassigned_members],
            [106],
        )
        self.assertTrue(view.is_configured)
        self.assertFalse(view.is_read_only)
        self.assertEqual(view.lock_version, 4)

    def test_management_view_is_read_only_after_round_starts(self):
        data = TeamQueryData(
            round_id=1,
            round_status="IN_PROGRESS",
            lock_version=4,
            participants=self.data.participants,
            teams=self.data.teams,
        )

        view = build_management_team_view(data)

        self.assertTrue(view.is_read_only)

    def test_management_view_reports_unconfigured_round(self):
        data = TeamQueryData(
            round_id=1,
            round_status="DRAFT",
            lock_version=0,
            participants=self.data.participants,
            teams=(),
        )

        view = build_management_team_view(data)

        self.assertFalse(view.is_configured)
        self.assertEqual(view.teams, ())
        self.assertEqual(len(view.unassigned_members), 6)

    def test_student_view_returns_only_students_own_team(self):
        view = build_student_team_view(self.data, user_id=2)

        self.assertTrue(view.is_configured)
        self.assertEqual(view.team.team_number, 1)
        self.assertEqual(
            [member.display_name for member in view.team.members],
            ["김민수", "이영희"],
        )

    def test_student_view_reports_team_not_configured_for_unassigned_student(self):
        view = build_student_team_view(self.data, user_id=6)

        self.assertFalse(view.is_configured)
        self.assertIsNone(view.team)

    def test_rejects_user_who_is_not_round_participant(self):
        with self.assertRaisesRegex(
            RoundParticipantNotFoundError,
            "not a participant",
        ):
            build_student_team_view(self.data, user_id=999)

    def test_rejects_unknown_participant_in_stored_team(self):
        data = TeamQueryData(
            round_id=1,
            round_status="DRAFT",
            lock_version=4,
            participants=self.data.participants,
            teams=(StoredTeam(1, "1팀", (101, 999)),),
        )

        with self.assertRaisesRegex(TeamQueryError, "unknown participant in team: 999"):
            build_management_team_view(data)

    def test_rejects_duplicate_assignment_in_stored_teams(self):
        data = TeamQueryData(
            round_id=1,
            round_status="DRAFT",
            lock_version=4,
            participants=self.data.participants,
            teams=(
                StoredTeam(1, "1팀", (101, 102)),
                StoredTeam(2, "2팀", (101, 103)),
            ),
        )

        with self.assertRaisesRegex(TeamQueryError, "assigned more than once: 101"):
            build_management_team_view(data)

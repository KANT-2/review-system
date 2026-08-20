from decimal import Decimal
from unittest import TestCase

from teams.application import AutoTeamBoardResult
from teams.contracts import (
    AutoAssignmentRequest,
    TeamContractError,
    TeamSaveRequest,
    auto_team_board_response,
    management_team_response,
    saved_team_board_response,
    student_team_response,
)
from teams.domain import TeamBoard, TeamDraft
from teams.queries import ManagementTeamView, StudentTeamView, TeamMemberView, TeamView


class TeamRequestContractTests(TestCase):
    def test_parses_auto_assignment_request(self):
        request = AutoAssignmentRequest.from_payload({"team_count": 3, "lock_version": 4})

        self.assertEqual(request.team_count, 3)
        self.assertEqual(request.lock_version, 4)

    def test_rejects_boolean_as_integer(self):
        with self.assertRaisesRegex(TeamContractError, "team_count must be an integer"):
            AutoAssignmentRequest.from_payload({"team_count": True, "lock_version": 4})

    def test_parses_team_save_request(self):
        request = TeamSaveRequest.from_payload(
            10,
            {
                "lock_version": 4,
                "imbalance_confirmed": True,
                "teams": [
                    {"team_number": 1, "name": " 1팀 ", "participant_ids": [101, 102]},
                    {"team_number": 2, "name": "2팀", "participant_ids": [103, 104]},
                ],
            },
        )

        self.assertEqual(request.board.round_id, 10)
        self.assertEqual(request.board.lock_version, 4)
        self.assertEqual(request.board.teams[0].name, "1팀")
        self.assertTrue(request.imbalance_confirmed)

    def test_defaults_imbalance_confirmation_to_false(self):
        request = TeamSaveRequest.from_payload(
            10,
            {
                "lock_version": 4,
                "teams": [
                    {"team_number": 1, "name": "1팀", "participant_ids": [101]},
                    {"team_number": 2, "name": "2팀", "participant_ids": [102]},
                ],
            },
        )

        self.assertFalse(request.imbalance_confirmed)

    def test_rejects_duplicate_team_numbers(self):
        with self.assertRaisesRegex(TeamContractError, "team_number must be unique"):
            TeamSaveRequest.from_payload(
                10,
                {
                    "lock_version": 4,
                    "teams": [
                        {"team_number": 1, "name": "1팀", "participant_ids": [101]},
                        {"team_number": 1, "name": "중복", "participant_ids": [102]},
                    ],
                },
            )

    def test_rejects_blank_team_name(self):
        with self.assertRaisesRegex(TeamContractError, "name must not be blank"):
            TeamSaveRequest.from_payload(
                10,
                {
                    "lock_version": 4,
                    "teams": [{"team_number": 1, "name": "  ", "participant_ids": [101]}],
                },
            )

    def test_rejects_non_integer_participant_id(self):
        with self.assertRaisesRegex(TeamContractError, "must be an integer"):
            TeamSaveRequest.from_payload(
                10,
                {
                    "lock_version": 4,
                    "teams": [{"team_number": 1, "name": "1팀", "participant_ids": ["101"]}],
                },
            )


class TeamResponseContractTests(TestCase):
    def setUp(self):
        self.board = TeamBoard(
            round_id=10,
            lock_version=4,
            teams=(
                TeamDraft(1, "1팀", (101, 102)),
                TeamDraft(2, "2팀", (103, 104)),
            ),
        )
        self.first_team = TeamView(
            1,
            "1팀",
            (
                TeamMemberView(101, "A001", "김민수"),
                TeamMemberView(102, "A002", "이영희"),
            ),
        )

    def test_serializes_auto_board_with_decimal_rounded_to_two_places(self):
        result = AutoTeamBoardResult(
            board=self.board,
            initial_standard_deviation=Decimal("4.2503"),
            final_standard_deviation=Decimal("2.125"),
            seeded_participant_count=4,
            initial_repeated_pair_count=2,
            final_repeated_pair_count=1,
            optimization_count=3,
            seed_scores={101: Decimal("4.567"), 102: None},
        )

        response = auto_team_board_response(result)

        # 화면 표시용이라 소수점 셋째 자리 이하는 반올림해서 보낸다 (RES-016과 달리
        # 편차/시드는 원본 정밀도를 보존해야 하는 값이 아니다).
        self.assertEqual(response["quality"]["initial_standard_deviation"], "4.25")
        self.assertEqual(response["quality"]["final_standard_deviation"], "2.13")
        self.assertEqual(response["teams"][0]["participant_ids"], [101, 102])
        self.assertEqual(response["seed_scores"], {"101": "4.57", "102": None})

    def test_serializes_saved_board_with_new_lock_version(self):
        response = saved_team_board_response(self.board)

        self.assertEqual(response["lock_version"], 4)
        self.assertEqual(len(response["teams"]), 2)

    def test_serializes_management_view(self):
        view = ManagementTeamView(
            round_id=10,
            round_status="DRAFT",
            lock_version=4,
            is_configured=True,
            is_read_only=False,
            teams=(self.first_team,),
            unassigned_members=(TeamMemberView(103, "A003", "박지훈"),),
            seed_scores={101: Decimal("3.1"), 102: None},
        )

        response = management_team_response(view)

        self.assertEqual(response["teams"][0]["members"][0]["display_name"], "김민수")
        self.assertEqual(response["unassigned_members"][0]["participant_id"], 103)
        self.assertEqual(response["seed_scores"], {"101": "3.10", "102": None})

    def test_student_response_never_includes_seed_scores(self):
        # 시드 점수는 튜터가 팀을 짤 때만 참고하는 값이다 - 다른 학생의 이전 점수를
        # 유추할 수 있는 값이라 학생 화면 응답에는 애초에 필드 자체가 없어야 한다.
        response = student_team_response(StudentTeamView(10, False, None))

        self.assertNotIn("seed_scores", response)

    def test_serializes_student_team_not_configured(self):
        response = student_team_response(StudentTeamView(10, False, None))

        self.assertEqual(
            response,
            {
                "round_id": 10,
                "round_status": "",
                "is_configured": False,
                "team": None,
                "teams": [],
                "my_participant_id": None,
            },
        )

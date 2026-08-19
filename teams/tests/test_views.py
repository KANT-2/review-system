import json
import re
from dataclasses import dataclass
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from django.test import RequestFactory

from teams.application import (
    AutoTeamBoardResult,
    RoundNotEditableError,
    TeamVersionConflictError,
)
from teams.contracts import AutoAssignmentRequest, TeamSaveRequest
from teams.domain import TeamBoard, TeamDraft
from teams.queries import (
    ManagementTeamView,
    StudentTeamView,
    TeamMemberView,
    TeamView,
)
from teams.services import ImbalanceConfirmationRequired, UnassignedParticipantsConfirmationRequired
from teams.views import (
    auto_assignment_view,
    management_team_page,
    management_team_view,
    save_team_view,
    student_team_page,
    student_team_view,
    team_ui_preview,
)


@dataclass
class FakeUser:
    id: int | None
    role: str | None
    is_authenticated: bool = True
    is_staff: bool = False


class FakeTeamsBackend:
    def __init__(self):
        self.saved_request = None
        self.auto_request = None
        self.auto_error = None
        self.save_error = None

    def get_student_team(self, user_id):
        team = TeamView(1, "1팀", (TeamMemberView(101, "A001", "김민수"),))
        return StudentTeamView(
            10,
            True,
            team,
            (team, TeamView(2, "2팀", (TeamMemberView(102, "A002", "이영희"),))),
            101,
        )

    def get_management_team(self, round_id):
        return ManagementTeamView(
            round_id,
            "DRAFT",
            4,
            True,
            False,
            (TeamView(1, "1팀", (TeamMemberView(101, "A001", "김민수"),)),),
            (),
        )

    def create_auto_assignment(self, round_id, request_data):
        if self.auto_error is not None:
            raise self.auto_error
        self.auto_request = request_data
        board = TeamBoard(
            round_id,
            request_data.lock_version,
            (TeamDraft(1, "1팀", (101,)), TeamDraft(2, "2팀", (102,))),
        )
        return AutoTeamBoardResult(
            board,
            Decimal("2"),
            Decimal("1"),
            2,
            1,
            0,
            1,
        )

    def save_team_configuration(self, round_id, actor_id, request_data):
        if self.save_error is not None:
            raise self.save_error
        self.saved_request = request_data
        self.saved_actor_id = actor_id
        return TeamBoard(round_id, request_data.board.lock_version + 1, request_data.board.teams)


class TeamsHttpViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.backend = FakeTeamsBackend()
        self.backend_patch = patch("teams.views.get_teams_backend", return_value=self.backend)
        self.backend_patch.start()
        self.addCleanup(self.backend_patch.stop)

    def test_student_can_get_own_team(self):
        request = self.factory.get("/student/team/")
        request.user = FakeUser(1, "student")

        response = student_team_view(request)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["team"]["name"], "1팀")
        self.assertEqual([team["name"] for team in payload["teams"]], ["1팀", "2팀"])
        self.assertEqual(payload["my_participant_id"], 101)

    def test_student_page_renders_all_team_workspace(self):
        request = self.factory.get("/teams/student/")
        request.user = FakeUser(1, "student")

        response = student_team_page(request)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("teams-initial-data", content)
        self.assertIn("팀 편성", content)

    def test_tutor_page_renders_management_workspace(self):
        request = self.factory.get("/teams/manage/rounds/10/")
        request.user = FakeUser(2, "tutor")

        response = management_team_page(request, 10)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "/teams/manage/rounds/10/teams/auto/",
            response.content.decode(),
        )
        self.assertIn("myParticipantId:null", response.content.decode())

    def test_management_page_offers_the_inline_member_search(self):
        """검색은 화면을 떠나지 않고 걸린다 - 편성 화면 자체가 입력을 들고 있어야 한다."""
        request = self.factory.get("/teams/manage/rounds/10/")
        request.user = FakeUser(2, "tutor")

        response = management_team_page(request, 10)

        content = response.content.decode()
        self.assertIn('id="memberSearch"', content)
        self.assertIn('type="search"', content)
        self.assertIn('id="searchMetric"', content)

    def test_preview_renders_without_database_backend(self):
        request = self.factory.get("/teams/preview/?role=tutor&state=unassigned")

        response = team_ui_preview(request)

        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("teams-initial-data", content)
        self.assertIn("previewMode:true", content)

    def test_management_page_hands_csrf_token_to_script(self):
        """CSRF 쿠키가 HttpOnly라 스크립트는 쿠키를 읽을 수 없다 - 서버가 페이지로
        토큰을 내려줘야 자동 배치·저장 요청이 403으로 막히지 않는다."""
        request = self.factory.get("/teams/manage/rounds/10/")
        request.user = FakeUser(2, "tutor")

        response = management_team_page(request, 10)

        content = response.content.decode()
        token = re.search(r'csrfToken:"([^"]*)"', content)
        self.assertIsNotNone(token, "페이지가 스크립트에 CSRF 토큰을 넘기지 않았습니다")
        self.assertGreaterEqual(len(token.group(1)), 32)

    def test_student_cannot_open_management_team_view(self):
        request = self.factory.get("/manage/rounds/10/teams/")
        request.user = FakeUser(1, "student")

        response = management_team_view(request, 10)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["error"]["code"], "permission_denied")

    def test_unauthenticated_user_receives_401(self):
        request = self.factory.get("/student/team/")
        request.user = FakeUser(None, None, is_authenticated=False)

        response = student_team_view(request)

        self.assertEqual(response.status_code, 401)

    def test_tutor_can_request_auto_assignment(self):
        request = self.factory.post(
            "/manage/rounds/10/teams/auto/",
            data=json.dumps({"team_count": 2, "lock_version": 4}),
            content_type="application/json",
        )
        request.user = FakeUser(2, "tutor")

        response = auto_assignment_view(request, 10)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.backend.auto_request, AutoAssignmentRequest(2, 4))
        self.assertEqual(len(json.loads(response.content)["teams"]), 2)

    def test_invalid_json_receives_400(self):
        request = self.factory.post(
            "/manage/rounds/10/teams/auto/",
            data="{invalid",
            content_type="application/json",
        )
        request.user = FakeUser(2, "tutor")

        response = auto_assignment_view(request, 10)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"]["code"], "invalid_request")

    def test_stale_auto_assignment_version_receives_409(self):
        self.backend.auto_error = TeamVersionConflictError("reload")
        request = self.factory.post(
            "/manage/rounds/10/teams/auto/",
            data=json.dumps({"team_count": 2, "lock_version": 3}),
            content_type="application/json",
        )
        request.user = FakeUser(2, "tutor")

        response = auto_assignment_view(request, 10)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content)["error"]["code"], "version_conflict")

    def test_tutor_can_save_team_configuration(self):
        request = self._save_request()

        response = save_team_view(request, 10)

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(self.backend.saved_request, TeamSaveRequest)
        self.assertEqual(self.backend.saved_actor_id, 2)
        self.assertEqual(json.loads(response.content)["lock_version"], 5)

    def test_imbalance_confirmation_receives_409(self):
        self.backend.save_error = ImbalanceConfirmationRequired("confirm imbalance")

        response = save_team_view(self._save_request(), 10)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "imbalance_confirmation_required",
        )

    def test_unassigned_confirmation_receives_409(self):
        self.backend.save_error = UnassignedParticipantsConfirmationRequired("confirm unassigned")

        response = save_team_view(self._save_request(), 10)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "unassigned_confirmation_required",
        )

    def test_version_conflict_receives_409(self):
        self.backend.save_error = TeamVersionConflictError("reload")

        response = save_team_view(self._save_request(), 10)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content)["error"]["code"], "version_conflict")

    def test_started_round_receives_409(self):
        self.backend.save_error = RoundNotEditableError("only DRAFT")

        response = save_team_view(self._save_request(), 10)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content)["error"]["code"], "round_not_editable")

    def test_staff_can_open_management_view_without_tutor_role(self):
        request = self.factory.get("/manage/rounds/10/teams/")
        request.user = FakeUser(3, "student", is_staff=True)

        response = management_team_view(request, 10)

        self.assertEqual(response.status_code, 200)

    def _save_request(self):
        request = self.factory.post(
            "/manage/rounds/10/teams/save/",
            data=json.dumps(
                {
                    "lock_version": 4,
                    "teams": [
                        {"team_number": 1, "name": "1팀", "participant_ids": [101]},
                        {"team_number": 2, "name": "2팀", "participant_ids": [102]},
                    ],
                }
            ),
            content_type="application/json",
        )
        request.user = FakeUser(2, "tutor")
        return request


class TeamsBackendConfigurationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_configured_backend_returns_not_found_without_active_round(self):
        request = self.factory.get("/teams/student/team/")
        request.user = FakeUser(1, "student")

        response = student_team_view(request)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "not_found",
        )

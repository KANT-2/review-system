import json
from typing import Protocol

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from teams.application import (
    AutoTeamBoardResult,
    RoundNotEditableError,
    TeamVersionConflictError,
)
from teams.contracts import (
    AutoAssignmentRequest,
    TeamContractError,
    TeamSaveRequest,
    auto_team_board_response,
    management_team_response,
    saved_team_board_response,
    student_team_response,
)
from teams.domain import TeamBoard
from teams.queries import (
    ManagementTeamView,
    RoundParticipantNotFoundError,
    StudentTeamView,
)
from teams.services import AssignmentValidationError, ImbalanceConfirmationRequired


class TeamsHttpBackend(Protocol):
    """실제 Django ORM 어댑터가 제공해야 하는 HTTP 연결 인터페이스다."""

    def get_student_team(self, user_id: int) -> StudentTeamView: ...

    def get_management_team(self, round_id: int) -> ManagementTeamView: ...

    def create_auto_assignment(
        self,
        round_id: int,
        request_data: AutoAssignmentRequest,
    ) -> AutoTeamBoardResult: ...

    def save_team_configuration(
        self,
        round_id: int,
        actor_id: int,
        request_data: TeamSaveRequest,
    ) -> TeamBoard: ...


class TeamsBackendNotConfiguredError(RuntimeError):
    """실제 ORM 연결이 아직 구성되지 않았음을 나타낸다."""


def get_teams_backend() -> TeamsHttpBackend:
    from teams.django_backend import build_django_teams_backend

    return build_django_teams_backend()


@require_GET
def team_ui_preview(request: HttpRequest) -> HttpResponse:
    """ORM 병합 전 로컬 UI 검토에만 사용하는 화면이다."""
    names = (
        "김민수",
        "이영희",
        "박지훈",
        "최서연",
        "정현우",
        "한지민",
        "윤서준",
        "임수아",
        "강도윤",
        "송하윤",
        "조현준",
        "배지우",
        "문시우",
        "오서윤",
        "신지호",
        "권나연",
        "안유진",
        "홍준서",
        "김서현",
        "이도윤",
        "박서아",
        "최준혁",
        "정다은",
        "한예준",
        "윤하린",
        "임도현",
        "강서진",
        "송민재",
        "조유나",
        "배현우",
        "문지아",
        "오준영",
        "신예린",
        "권도하",
        "안수빈",
    )
    teams = []
    for team_index in range(7):
        members = [
            {
                "participant_id": index + 101,
                "student_number": f"A{index + 1:03d}",
                "display_name": name,
            }
            for index, name in enumerate(names)
            if index % 7 == team_index
        ]
        teams.append(
            {"team_number": team_index + 1, "name": f"{team_index + 1}팀", "members": members}
        )
    role = request.GET.get("role", "tutor")
    state = request.GET.get("state", "configured")
    configured = state != "empty"
    unassigned_members = []
    if role == "tutor" and state == "unassigned":
        unassigned_members = teams[-1]["members"][-3:]
        teams[-1]["members"] = teams[-1]["members"][:-3]
    return render(
        request,
        "teams/workspace.html",
        {
            "role": role,
            "my_participant_id": 101 if role == "student" else None,
            "team_data": {
                "round_id": 10,
                "round_status": "DRAFT" if configured else "COMPLETED",
                "lock_version": 1,
                "is_configured": configured,
                "is_read_only": False,
                "teams": teams if configured else [],
                "unassigned_members": unassigned_members,
                "my_participant_id": 101,
            },
            "preview_mode": True,
        },
    )


@require_GET
def student_team_page(request: HttpRequest) -> HttpResponse:
    permission_error = _permission_error(request, allowed_roles={"student"})
    if permission_error is not None:
        return permission_error
    try:
        view = get_teams_backend().get_student_team(request.user.id)
    except LookupError:
        return render(
            request,
            "teams/workspace.html",
            {
                "role": "student",
                "team_data": {
                    "round_id": None,
                    "round_status": "NONE",
                    "lock_version": 0,
                    "is_configured": False,
                    "is_read_only": True,
                    "teams": [],
                    "unassigned_members": [],
                    "my_participant_id": None,
                },
                "my_participant_id": None,
            },
        )
    return render(
        request,
        "teams/workspace.html",
        {
            "role": "student",
            "team_data": student_team_response(view),
            "my_participant_id": view.participant_id,
        },
    )


@require_GET
def management_team_page(request: HttpRequest, round_id: int) -> HttpResponse:
    permission_error = _permission_error(request, allowed_roles={"tutor"})
    if permission_error is not None:
        return permission_error
    try:
        view = get_teams_backend().get_management_team(round_id)
    except LookupError:
        return _error_response("not_found", "회차가 없습니다.", 404)
    return render(
        request,
        "teams/workspace.html",
        {
            "role": "tutor",
            "team_data": management_team_response(view),
            "auto_url": f"/teams/manage/rounds/{round_id}/teams/auto/",
            "save_url": f"/teams/manage/rounds/{round_id}/teams/save/",
        },
    )


@require_GET
def student_team_view(request: HttpRequest) -> JsonResponse:
    permission_error = _permission_error(request, allowed_roles={"student"})
    if permission_error is not None:
        return permission_error
    try:
        view = get_teams_backend().get_student_team(request.user.id)
        return JsonResponse(student_team_response(view))
    except RoundParticipantNotFoundError as error:
        return _error_response("not_found", str(error), 404)
    except LookupError as error:
        return _error_response("not_found", str(error), 404)


@require_GET
def management_team_view(request: HttpRequest, round_id: int) -> JsonResponse:
    permission_error = _permission_error(request, allowed_roles={"tutor"})
    if permission_error is not None:
        return permission_error
    try:
        view = get_teams_backend().get_management_team(round_id)
        return JsonResponse(management_team_response(view))
    except LookupError as error:
        return _error_response("not_found", str(error), 404)


@require_POST
def auto_assignment_view(request: HttpRequest, round_id: int) -> JsonResponse:
    permission_error = _permission_error(request, allowed_roles={"tutor"})
    if permission_error is not None:
        return permission_error
    try:
        request_data = AutoAssignmentRequest.from_payload(_json_payload(request))
        result = get_teams_backend().create_auto_assignment(round_id, request_data)
        return JsonResponse(auto_team_board_response(result))
    except (TeamContractError, AssignmentValidationError) as error:
        return _error_response("invalid_request", str(error), 400)
    except TeamVersionConflictError as error:
        return _error_response("version_conflict", str(error), 409)
    except RoundNotEditableError as error:
        return _error_response("round_not_editable", str(error), 409)
    except LookupError as error:
        return _error_response("not_found", str(error), 404)


@require_POST
def save_team_view(request: HttpRequest, round_id: int) -> JsonResponse:
    permission_error = _permission_error(request, allowed_roles={"tutor"})
    if permission_error is not None:
        return permission_error
    try:
        request_data = TeamSaveRequest.from_payload(round_id, _json_payload(request))
        board = get_teams_backend().save_team_configuration(
            round_id,
            request.user.id,
            request_data,
        )
        return JsonResponse(saved_team_board_response(board))
    except ImbalanceConfirmationRequired as error:
        return _error_response("imbalance_confirmation_required", str(error), 409)
    except TeamVersionConflictError as error:
        return _error_response("version_conflict", str(error), 409)
    except RoundNotEditableError as error:
        return _error_response("round_not_editable", str(error), 409)
    except (TeamContractError, AssignmentValidationError) as error:
        return _error_response("invalid_request", str(error), 400)
    except LookupError as error:
        return _error_response("not_found", str(error), 404)


def _json_payload(request: HttpRequest) -> dict[str, object]:
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise TeamContractError("request body must be valid JSON") from error
    if not isinstance(payload, dict):
        raise TeamContractError("request body must be a JSON object")
    return payload


def _permission_error(
    request: HttpRequest,
    *,
    allowed_roles: set[str],
) -> JsonResponse | None:
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return _error_response("authentication_required", "login is required", 401)
    # 권한 정의는 accounts가 소유하고 teams는 전달받은 역할과 staff 여부만 사용한다.
    role = getattr(user, "role", None)
    normalized_role = role.lower() if isinstance(role, str) else None
    if not getattr(user, "is_staff", False) and normalized_role not in allowed_roles:
        return _error_response("permission_denied", "permission denied", 403)
    return None


def _error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def _service_unavailable_response() -> JsonResponse:
    return _error_response(
        "teams_backend_not_configured",
        "팀 편성 데이터 연결이 아직 준비되지 않았습니다.",
        503,
    )

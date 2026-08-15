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


def get_teams_backend() -> TeamsHttpBackend:
    """rounds·results·audit 모델 병합 후 실제 ORM 백엔드로 교체한다."""
    raise RuntimeError("Teams Django backend is not configured")


@require_GET
def student_team_page(request: HttpRequest) -> HttpResponse:
    permission_error = _permission_error(request, allowed_roles={"STUDENT"})
    if permission_error is not None:
        return permission_error
    view = get_teams_backend().get_student_team(request.user.id)
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
    permission_error = _permission_error(request, allowed_roles={"TUTOR"})
    if permission_error is not None:
        return permission_error
    view = get_teams_backend().get_management_team(round_id)
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
    permission_error = _permission_error(request, allowed_roles={"STUDENT"})
    if permission_error is not None:
        return permission_error
    try:
        view = get_teams_backend().get_student_team(request.user.id)
        return JsonResponse(student_team_response(view))
    except RoundParticipantNotFoundError as error:
        return _error_response("not_found", str(error), 404)


@require_GET
def management_team_view(request: HttpRequest, round_id: int) -> JsonResponse:
    permission_error = _permission_error(request, allowed_roles={"TUTOR"})
    if permission_error is not None:
        return permission_error
    try:
        view = get_teams_backend().get_management_team(round_id)
        return JsonResponse(management_team_response(view))
    except LookupError as error:
        return _error_response("not_found", str(error), 404)


@require_POST
def auto_assignment_view(request: HttpRequest, round_id: int) -> JsonResponse:
    permission_error = _permission_error(request, allowed_roles={"TUTOR"})
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
    permission_error = _permission_error(request, allowed_roles={"TUTOR"})
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
    if not getattr(user, "is_staff", False) and getattr(user, "role", None) not in allowed_roles:
        return _error_response("permission_denied", "permission denied", 403)
    return None


def _error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)

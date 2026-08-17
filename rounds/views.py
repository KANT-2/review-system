from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import User
from accounts.permissions import is_operations_user
from reviews.models import ReviewSubmission
from rounds.forms import EvaluationRoundForm
from rounds.models import EvaluationRound
from rounds.services import (
    complete_round,
    get_review_progress,
    round_start_errors,
    rounds_dashboard_rows,
    save_round,
    start_round,
)


def _require_operations(user):
    if not is_operations_user(user):
        raise PermissionDenied


@login_required
def operations_dashboard(request):
    _require_operations(request.user)
    current = rounds_dashboard_rows().filter(status=EvaluationRound.Status.IN_PROGRESS).first()
    latest_draft = rounds_dashboard_rows().filter(status=EvaluationRound.Status.DRAFT).first()
    completed = rounds_dashboard_rows().filter(status=EvaluationRound.Status.COMPLETED)[:5]
    progress = get_review_progress(current) if current else None
    pending_approvals = User.objects.filter(
        role=User.Role.STUDENT,
        approval_status=User.ApprovalStatus.PENDING,
        emailaddress__verified=True,
        emailaddress__primary=True,
    ).count()
    return render(
        request,
        "rounds/dashboard.html",
        {
            "current_round": current,
            "latest_draft": latest_draft,
            "completed_rounds": completed,
            "progress": progress,
            "pending_approvals": pending_approvals,
        },
    )


@login_required
def round_list(request):
    _require_operations(request.user)
    return render(request, "rounds/list.html", {"rounds": rounds_dashboard_rows()})


@login_required
@require_http_methods(["GET", "POST"])
def round_edit(request, round_id=None):
    _require_operations(request.user)
    round_obj = get_object_or_404(EvaluationRound, pk=round_id) if round_id else None
    if round_obj and round_obj.status != EvaluationRound.Status.DRAFT:
        return render(
            request,
            "rounds/form.html",
            {"round_obj": round_obj, "read_only": True, "form": None},
        )
    form = EvaluationRoundForm(request.POST or None, instance=round_obj)
    if request.method == "POST" and form.is_valid():
        try:
            saved = save_round(form=form, actor=request.user)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "회차 정보를 저장했습니다.")
            return redirect("rounds:edit", round_id=saved.pk)
    return render(
        request,
        "rounds/form.html",
        {"round_obj": round_obj, "form": form, "read_only": False},
    )


@login_required
@require_POST
def round_start(request, round_id):
    _require_operations(request.user)
    try:
        start_round(round_id=round_id, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "회차를 시작했습니다. 참가자·팀·질문지가 동결됩니다.")
    return redirect("rounds:reviews", round_id=round_id)


def _participant_progress_rows(round_obj):
    team_count = round_obj.teams.count()
    completed = (
        ReviewSubmission.objects.filter(round=round_obj)
        .values("evaluator_id", "review_type")
        .annotate(count=Count("id"))
    )
    completed_map = {(row["evaluator_id"], row["review_type"]): row["count"] for row in completed}
    rows = []
    participants = round_obj.participants.select_related("team_membership__team").all()
    for participant in participants:
        team_size = (
            participant.team_membership.team.memberships.count()
            if hasattr(participant, "team_membership")
            else 0
        )
        team_expected = max(team_count - 1, 0)
        peer_expected = max(team_size - 1, 0)
        rows.append(
            {
                "participant": participant,
                "team_expected": team_expected,
                "team_completed": completed_map.get(
                    (participant.pk, ReviewSubmission.ReviewType.TEAM), 0
                ),
                "peer_expected": peer_expected,
                "peer_completed": completed_map.get(
                    (participant.pk, ReviewSubmission.ReviewType.PEER), 0
                ),
            }
        )
    return rows


@login_required
def round_reviews(request, round_id):
    _require_operations(request.user)
    round_obj = get_object_or_404(
        EvaluationRound.objects.prefetch_related(
            "participants",
            "teams__memberships",
            "team_template__questions",
            "peer_template__questions",
        ),
        pk=round_id,
    )
    progress = get_review_progress(round_obj)
    return render(
        request,
        "rounds/reviews.html",
        {
            "round_obj": round_obj,
            "progress": progress,
            "start_errors": round_start_errors(round_obj)
            if round_obj.status == EvaluationRound.Status.DRAFT
            else [],
            "participant_rows": _participant_progress_rows(round_obj),
        },
    )


@login_required
@require_POST
def round_complete(request, round_id):
    _require_operations(request.user)
    try:
        complete_round(
            round_id=round_id,
            actor=request.user,
            force_confirmed=request.POST.get("force_confirmed") == "1",
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "회차를 마감했습니다. 이제 채점을 실행할 수 있습니다.")
        return redirect("rounds:results", round_id=round_id)
    return redirect("rounds:reviews", round_id=round_id)

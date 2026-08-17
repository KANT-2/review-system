from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import is_student_user
from reviews.forms import ReviewForm
from reviews.models import ReviewSubmission
from reviews.services import (
    DuplicateReviewError,
    current_participation,
    get_submission,
    own_submission,
    participation_for_round,
    peer_targets,
    questions_for,
    review_window_state,
    started_participations,
    submit_review,
    team_targets,
)
from rounds.models import EvaluationRound


def _participant_or_none(request):
    if not is_student_user(request.user):
        raise PermissionDenied
    return current_participation(request.user)


def _list_page(request, *, review_type):
    participant = _participant_or_none(request)
    targets = team_targets(participant) if review_type == "TEAM" else peer_targets(participant)
    return render(
        request,
        "reviews/list.html",
        {
            "participant": participant,
            "targets": targets,
            "review_type": review_type,
            "window_state": review_window_state(participant.round) if participant else None,
            "completed_count": sum(target.completed for target in targets),
        },
    )


@login_required
def team_review_list(request):
    return _list_page(request, review_type=ReviewSubmission.ReviewType.TEAM)


@login_required
def peer_review_list(request):
    return _list_page(request, review_type=ReviewSubmission.ReviewType.PEER)


def _form_page(request, *, review_type, target_id):
    participant = _participant_or_none(request)
    if not participant:
        raise PermissionDenied("현재 회차 참가자가 아닙니다.")
    targets = team_targets(participant) if review_type == "TEAM" else peer_targets(participant)
    target = next((row for row in targets if row.pk == target_id), None)
    if not target:
        raise PermissionDenied("평가할 수 없는 대상입니다.")
    existing = get_submission(participant, review_type, target_id)
    questions = list(questions_for(participant.round, review_type))
    form = ReviewForm(request.POST or None, questions=questions)
    if request.method == "POST":
        if existing:
            messages.info(request, "이미 제출한 평가입니다.")
        elif form.is_valid():
            try:
                submit_review(
                    participant=participant,
                    review_type=review_type,
                    target_id=target_id,
                    answers=form.answer_values(),
                )
            except DuplicateReviewError:
                messages.info(request, "동일 대상 평가가 이미 제출되었습니다.")
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, "평가를 제출했습니다. 제출 후에는 수정할 수 없습니다.")
                return redirect(
                    "reviews:team-list" if review_type == "TEAM" else "reviews:peer-list"
                )
    return render(
        request,
        "reviews/form.html",
        {
            "participant": participant,
            "target": target,
            "review_type": review_type,
            "form": form,
            "questions": questions,
            "existing": existing,
            "readonly_answers": existing.answers.all() if existing else [],
            "window_state": review_window_state(participant.round),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def team_review_form(request, target_id):
    return _form_page(request, review_type=ReviewSubmission.ReviewType.TEAM, target_id=target_id)


@login_required
@require_http_methods(["GET", "POST"])
def peer_review_form(request, target_id):
    return _form_page(request, review_type=ReviewSubmission.ReviewType.PEER, target_id=target_id)


def _submission_map(participant, review_type):
    """대상 id → 제출 id. 지난 회차 응답을 읽기 전용으로 열기 위해 쓴다."""
    field = "target_team_id" if review_type == "TEAM" else "target_participant_id"
    return {
        getattr(submission, field): submission.pk
        for submission in ReviewSubmission.objects.filter(
            round=participant.round, evaluator=participant, review_type=review_type
        )
    }


@login_required
def review_status(request):
    if not is_student_user(request.user):
        raise PermissionDenied
    participations = started_participations(request.user)
    requested = request.GET.get("round")
    participant = None
    if requested and requested.isdigit():
        participant = participation_for_round(request.user, int(requested))
    if participant is None:
        # 기본은 진행 중 회차, 없으면 가장 최근에 시작한 회차를 연다.
        participant = current_participation(request.user) or (
            participations[0] if participations else None
        )
    team_rows = team_targets(participant)
    peer_rows = peer_targets(participant)
    is_current = bool(
        participant and participant.round.status == EvaluationRound.Status.IN_PROGRESS
    )
    return render(
        request,
        "reviews/status.html",
        {
            "participant": participant,
            "participations": participations,
            "selected_round_id": participant.round_id if participant else None,
            "is_current_round": is_current,
            "team_rows": team_rows,
            "peer_rows": peer_rows,
            "team_submissions": _submission_map(participant, "TEAM") if participant else {},
            "peer_submissions": _submission_map(participant, "PEER") if participant else {},
            "team_completed": sum(row.completed for row in team_rows),
            "peer_completed": sum(row.completed for row in peer_rows),
        },
    )


@login_required
def submission_detail(request, submission_id):
    """본인이 제출한 응답 읽기 전용 조회 - 지난 회차도 볼 수 있다(PR-008)."""
    if not is_student_user(request.user):
        raise PermissionDenied
    submission = own_submission(request.user, submission_id)
    if submission is None:
        raise Http404("제출을 찾을 수 없습니다.")
    target = (
        submission.target_team.name
        if submission.review_type == ReviewSubmission.ReviewType.TEAM
        else submission.target_participant.display_name_snapshot
    )
    return render(
        request,
        "reviews/submission_detail.html",
        {
            "submission": submission,
            "target_label": target,
            "answers": submission.answers.all(),
        },
    )

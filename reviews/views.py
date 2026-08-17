from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import is_student_user
from reviews.forms import ReviewForm
from reviews.models import ReviewSubmission
from reviews.services import (
    DuplicateReviewError,
    current_participation,
    get_submission,
    peer_targets,
    questions_for,
    review_window_state,
    submit_review,
    team_targets,
)


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


@login_required
def review_status(request):
    participant = _participant_or_none(request)
    team_rows = team_targets(participant)
    peer_rows = peer_targets(participant)
    return render(
        request,
        "reviews/status.html",
        {
            "participant": participant,
            "team_rows": team_rows,
            "peer_rows": peer_rows,
            "team_completed": sum(row.completed for row in team_rows),
            "peer_completed": sum(row.completed for row in peer_rows),
        },
    )

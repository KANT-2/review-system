from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import is_student_user
from reviews.forms import ReviewForm
from reviews.models import ReviewSubmission
from reviews.services import (
    DuplicateReviewError,
    current_participation,
    final_submit,
    final_submit_state,
    get_submission,
    is_final_submitted,
    lock_submission,
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
            "final_state": final_submit_state(participant, review_type) if participant else None,
        },
    )


@login_required
def team_review_list(request):
    return _list_page(request, review_type=ReviewSubmission.ReviewType.TEAM)


@login_required
def peer_review_list(request):
    return _list_page(request, review_type=ReviewSubmission.ReviewType.PEER)


@login_required
def review_home(request):
    """팀 평가·개인 평가를 한 화면에서 보여주는 통합 페이지.

    기존 team-list/peer-list 화면은 그대로 남아 있고(직접 링크·즐겨찾기 호환), 이 화면은
    두 목록을 한 번에 모아 보여주는 진입점 역할만 한다.
    """
    participant = _participant_or_none(request)
    team_targets_list = team_targets(participant)
    peer_targets_list = peer_targets(participant)
    return render(
        request,
        "reviews/home.html",
        {
            "participant": participant,
            "team_targets": team_targets_list,
            "peer_targets": peer_targets_list,
            "window_state": review_window_state(participant.round) if participant else None,
            "team_completed_count": sum(target.completed for target in team_targets_list),
            "peer_completed_count": sum(target.completed for target in peer_targets_list),
            "team_final_state": (
                final_submit_state(participant, ReviewSubmission.ReviewType.TEAM)
                if participant
                else None
            ),
            "peer_final_state": (
                final_submit_state(participant, ReviewSubmission.ReviewType.PEER)
                if participant
                else None
            ),
        },
    )


def _initial_from(submission):
    """이미 낸 답변을 폼에 채워 넣는다 - 수정 화면에서 처음부터 다시 쓰지 않게."""
    return {
        f"question_{answer.question_id}": (
            answer.rating_value if answer.rating_value is not None else answer.text_value
        )
        for answer in submission.answers.all()
    }


def _form_page(request, *, review_type, target_id):
    # panel=1 이면 통합 화면(reviews:home)의 슬라이드 패널이 fetch로 이 화면을 불러온 것이다 -
    # 레이아웃 없는 조각을 돌려주고, 저장 성공은 204로만 알린다(패널 쪽 JS가 처리).
    panel = request.GET.get("panel") == "1" or request.POST.get("panel") == "1"
    participant = _participant_or_none(request)
    if not participant:
        raise PermissionDenied("현재 회차 참가자가 아닙니다.")
    targets = team_targets(participant) if review_type == "TEAM" else peer_targets(participant)
    target = next((row for row in targets if row.pk == target_id), None)
    if not target:
        raise PermissionDenied("평가할 수 없는 대상입니다.")
    existing = get_submission(participant, review_type, target_id)
    questions = list(questions_for(participant.round, review_type))
    finalized = is_final_submitted(participant, review_type)
    locked = bool(existing and existing.locked_at)
    initial = _initial_from(existing) if existing else None
    form = ReviewForm(request.POST or None, questions=questions, initial=initial)
    if request.method == "POST":
        if finalized:
            messages.info(request, "최종 제출한 평가는 수정할 수 없습니다.")
        elif locked:
            messages.info(request, "확정된 평가는 수정할 수 없습니다.")
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
                if panel:
                    # 본문 없이 204만 돌려주면 패널 JS가 성공으로 보고 화면을 새로고침한다.
                    return HttpResponse(status=204)
                messages.success(
                    request,
                    "평가를 수정했습니다." if existing else "평가를 제출했습니다.",
                )
                return redirect(
                    "reviews:team-list" if review_type == "TEAM" else "reviews:peer-list"
                )
    context = {
        "participant": participant,
        "target": target,
        "review_type": review_type,
        "form": form,
        "questions": questions,
        "existing": existing,
        "finalized": finalized,
        "locked": locked,
        "readonly_answers": existing.answers.all() if existing else [],
        "window_state": review_window_state(participant.round),
        "panel": panel,
    }
    template = "reviews/_form_panel.html" if panel else "reviews/form.html"
    return render(request, template, context)


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
@require_http_methods(["POST"])
def review_final_submit(request, review_type):
    """유형별 최종 제출 - 되돌릴 수 없다."""
    if review_type not in ReviewSubmission.ReviewType.values:
        raise Http404("알 수 없는 평가 유형입니다.")
    participant = _participant_or_none(request)
    if not participant:
        raise PermissionDenied("현재 회차 참가자가 아닙니다.")
    try:
        final_submit(participant=participant, review_type=review_type)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "최종 제출했습니다. 이제 이 평가는 수정할 수 없습니다.")
    return redirect("reviews:home")


@login_required
@require_http_methods(["POST"])
def peer_review_lock(request, target_id):
    """개인 평가는 대상 1명 단위로도 확정할 수 있다 - 유형 전체를 잠그는
    final-submit과 달리 그 사람 평가 하나만 더 이상 못 고치게 한다."""
    participant = _participant_or_none(request)
    if not participant:
        raise PermissionDenied("현재 회차 참가자가 아닙니다.")
    try:
        lock_submission(
            participant=participant,
            review_type=ReviewSubmission.ReviewType.PEER,
            target_id=target_id,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "해당 평가를 확정했습니다. 이제 이 평가는 수정할 수 없습니다.")
    return redirect("reviews:home")


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

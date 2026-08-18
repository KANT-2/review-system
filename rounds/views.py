from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import User
from accounts.permissions import is_operations_user
from reviews.models import ReviewAnswer, ReviewSubmission
from rounds.forms import EvaluationRoundForm, QuestionTemplateForm, TemplateQuestionFormSet
from rounds.models import EvaluationRound, QuestionTemplate, TemplateQuestion
from rounds.services import (
    complete_round,
    copy_question_template,
    delete_question_template,
    delete_round,
    get_review_progress,
    question_template_rows,
    reopen_round,
    revert_round_to_draft,
    round_start_errors,
    rounds_dashboard_rows,
    save_question_template,
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
    # 승인 화면(accounts:tutor_dashboard)이 세는 기준과 같아야 배지 숫자가 목록과 맞는다.
    pending_approvals = User.objects.filter(
        role=User.Role.STUDENT,
        approval_status=User.ApprovalStatus.PENDING,
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
            "text_answer_count": _text_answers(round_obj).count(),
        },
    )


def _text_answers(round_obj):
    """회차의 자유 서술형 답변만 모은다.

    빈 문자열 제외는 방어용이다 - reviews_answer_exactly_one_value 제약이 이미 막고 있다.
    """
    return (
        ReviewAnswer.objects.filter(
            submission__round=round_obj,
            question__response_type=TemplateQuestion.ResponseType.TEXT,
        )
        .exclude(text_value="")
        .select_related(
            "question",
            "submission__evaluator",
            "submission__target_team",
            "submission__target_participant",
        )
        .order_by("question__display_order", "submission__submitted_at")
    )


@login_required
def round_text_answers(request, round_id):
    """서술형 응답 열람 - 운영자 전용(RES-013).

    학생 화면에는 원문도 작성자도 나가지 않는다. 이 화면이 없으면 서술형 문항을 받아도
    읽을 방법이 없어서 문항 유형 자체가 무의미해진다.
    """
    _require_operations(request.user)
    round_obj = get_object_or_404(EvaluationRound, pk=round_id)
    grouped = {}
    for answer in _text_answers(round_obj):
        submission = answer.submission
        grouped.setdefault(answer.question, []).append(
            {
                "evaluator": submission.evaluator.display_name_snapshot,
                "target": (
                    submission.target_team.name
                    if submission.review_type == ReviewSubmission.ReviewType.TEAM
                    else submission.target_participant.display_name_snapshot
                ),
                "review_type": submission.review_type,
                "submitted_at": submission.submitted_at,
                "text": answer.text_value,
            }
        )
    return render(
        request,
        "rounds/text_answers.html",
        {
            "round_obj": round_obj,
            "question_groups": [
                {"question": question, "answers": rows} for question, rows in grouped.items()
            ],
            "total_count": sum(len(rows) for rows in grouped.values()),
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


@login_required
def template_list(request):
    """문항 템플릿 목록 - 운영자가 admin 없이 평가 문항을 관리하는 화면."""
    _require_operations(request.user)
    return render(request, "rounds/template_list.html", {"templates": question_template_rows()})


@login_required
@require_http_methods(["GET", "POST"])
def template_edit(request, template_id=None):
    _require_operations(request.user)
    template = get_object_or_404(QuestionTemplate, pk=template_id) if template_id else None
    locked = bool(template and template.is_locked)
    form = QuestionTemplateForm(request.POST or None, instance=template)
    formset = TemplateQuestionFormSet(request.POST or None, instance=template)
    if request.method == "POST":
        if locked:
            messages.error(request, "시작된 회차가 사용하는 템플릿은 수정할 수 없습니다.")
            return redirect("rounds:template-list")
        if form.is_valid() and formset.is_valid():
            try:
                saved = save_question_template(form=form, formset=formset, actor=request.user)
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
            else:
                messages.success(request, f"'{saved.name}' 템플릿을 저장했습니다.")
                return redirect("rounds:template-list")
    return render(
        request,
        "rounds/template_form.html",
        {"form": form, "formset": formset, "template": template, "locked": locked},
    )


@login_required
@require_POST
def template_copy(request, template_id):
    _require_operations(request.user)
    copy = copy_question_template(template_id=template_id, actor=request.user)
    messages.success(request, f"'{copy.name}'으로 복제했습니다. 내용을 수정해 주세요.")
    return redirect("rounds:template-edit", template_id=copy.pk)


@login_required
@require_POST
def template_delete(request, template_id):
    _require_operations(request.user)
    try:
        delete_question_template(template_id=template_id, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "템플릿을 삭제했습니다.")
    return redirect("rounds:template-list")


def _round_lifecycle_action(request, round_id, *, action, success_message):
    """회차 상태를 되돌리는 세 가지 동작이 결과 처리 방식이 같아 한곳에 모았다."""
    _require_operations(request.user)
    try:
        action(round_id=round_id, actor=request.user)
    except (EvaluationRound.DoesNotExist, ValidationError) as error:
        messages.error(request, " ".join(getattr(error, "messages", [str(error)])))
        return redirect("rounds:list")
    messages.success(request, success_message)
    return redirect("rounds:list")


@login_required
@require_POST
def round_delete(request, round_id):
    return _round_lifecycle_action(
        request, round_id, action=delete_round, success_message="회차를 삭제했습니다."
    )


@login_required
@require_POST
def round_revert(request, round_id):
    return _round_lifecycle_action(
        request,
        round_id,
        action=revert_round_to_draft,
        success_message="회차를 준비 중으로 되돌렸습니다.",
    )


@login_required
@require_POST
def round_reopen(request, round_id):
    return _round_lifecycle_action(
        request, round_id, action=reopen_round, success_message="회차를 다시 열었습니다."
    )


@login_required
@require_POST
def send_submission_reminders_view(request, round_id):
    """특정 회차 미제출 수강생들에게 독촉 이메일을 일괄 발송합니다."""
    _require_operations(request.user)
    round_obj = get_object_or_404(EvaluationRound, pk=round_id)

    from accounts.email_services import send_submission_reminder_email
    from accounts.models import User

    students = User.objects.filter(role=User.Role.STUDENT, is_active=True)
    sent_count = 0
    for student in students:
        name = student.first_name if student.first_name else student.email
        send_submission_reminder_email(round_obj, name, student.email)
        sent_count += 1

    messages.success(request, f"총 {sent_count}명의 미제출 수강생에게 독촉 이메일이 발송되었습니다.")
    return redirect("rounds:reviews", round_id=round_id)


from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import User
from accounts.permissions import is_operations_user
from reviews.forms import ReviewForm
from reviews.models import ReviewSubmission, TutorReview
from reviews.services import (
    get_tutor_review,
    submit_tutor_review,
    tutor_review_questions,
    tutor_review_targets,
    tutor_reviewable,
)
from rounds.forms import EvaluationRoundForm, QuestionTemplateForm, TemplateQuestionFormSet
from rounds.models import EvaluationRound, QuestionTemplate
from rounds.services import (
    complete_round,
    copy_question_template,
    delete_question_template,
    delete_round,
    get_review_progress,
    question_template_rows,
    reopen_round,
    revert_round_to_draft,
    round_start_checks,
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
    # 승인 화면(accounts:account_admin)이 세는 기준과 같아야 배지 숫자가 목록과 맞는다.
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
def results_entry(request):
    """사이드바 '결과 공개' - 가장 최근 완료 회차의 결과 화면으로 바로 이동한다.

    채점은 완료된 회차에서만 가능하므로(results.application.calculate_round),
    완료된 회차가 하나도 없으면 공개할 결과 자체가 없다.
    """
    _require_operations(request.user)
    latest_completed = (
        EvaluationRound.objects.filter(status=EvaluationRound.Status.COMPLETED)
        .order_by("-completed_at")
        .first()
    )
    if not latest_completed:
        messages.info(
            request,
            "아직 완료된 회차가 없어 결과를 공개할 수 없습니다. 회차를 마감한 뒤 다시 시도해 주세요.",
        )
        return redirect("rounds:list")
    return redirect("rounds:results", round_id=latest_completed.pk)


def _participant_count(form, round_obj):
    """회차 설정 화면에 보여줄 참가자 수 - 저장했을 때 실제로 들어갈 인원과 같아야 한다."""
    user_ids = set(form.fields["participants"].queryset.values_list("pk", flat=True))
    if round_obj:
        user_ids |= set(round_obj.participants.values_list("user_id", flat=True))
    return len(user_ids)


def _template_previews():
    """회차 설정 화면의 '미리보기' 창에 넣을 템플릿별 문항 목록.

    선택하기 전에 어떤 문항이 들어 있는지 확인할 수 있어야 잘못된 템플릿을 붙이지 않는다.
    """
    return {
        str(template.pk): {
            "name": template.name,
            "category": template.get_category_display(),
            "description": template.description,
            "questions": [
                {
                    "prompt": question.prompt,
                    "response_type": question.get_response_type_display(),
                    "competency": (
                        question.get_competency_display() if question.competency else ""
                    ),
                    "is_required": question.is_required,
                }
                for question in template.questions.all()
            ],
        }
        for template in QuestionTemplate.objects.prefetch_related("questions")
    }


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
            messages.success(request, "회차 정보를 저장했습니다. 이제 팀을 편성해 주세요.")
            return redirect("rounds:teams", round_id=saved.pk)
    return render(
        request,
        "rounds/form.html",
        {
            "round_obj": round_obj,
            "form": form,
            "read_only": False,
            "participant_count": _participant_count(form, round_obj),
            "template_previews": _template_previews(),
        },
    )


@login_required
@require_POST
def round_start(request, round_id):
    _require_operations(request.user)
    try:
        start_round(
            round_id=round_id,
            actor=request.user,
            force_confirmed=request.POST.get("force_confirmed") == "1",
        )
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
        is_unassigned = not hasattr(participant, "team_membership")
        team_size = 0 if is_unassigned else participant.team_membership.team.memberships.count()
        team_expected = max(team_count - 1, 0)
        peer_expected = max(team_size - 1, 0)
        rows.append(
            {
                "participant": participant,
                "is_unassigned": is_unassigned,
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
    start_checks = (
        round_start_checks(round_obj) if round_obj.status == EvaluationRound.Status.DRAFT else []
    )
    return render(
        request,
        "rounds/reviews.html",
        {
            "round_obj": round_obj,
            "progress": progress,
            "start_blocking": [check.message for check in start_checks if not check.confirmable],
            "start_confirmable": [check.message for check in start_checks if check.confirmable],
            "participant_rows": _participant_progress_rows(round_obj),
            "tutor_review_count": TutorReview.objects.filter(
                round=round_obj, evaluator=request.user
            ).count(),
        },
    )


@login_required
def tutor_review_list(request, round_id):
    """튜터 개인평가 - 회차 참가자 목록에서 한 명씩 평가한다.

    학생끼리 하는 개인 평가와 저장 위치가 다르고(reviews.TutorReview), 지금은 기록만 남는다
    - 최종점수 계산에는 반영하지 않는다.
    """
    _require_operations(request.user)
    round_obj = get_object_or_404(EvaluationRound, pk=round_id)
    targets = tutor_review_targets(round_obj, request.user) if tutor_reviewable(round_obj) else []
    return render(
        request,
        "rounds/tutor_review_list.html",
        {
            "round_obj": round_obj,
            "targets": targets,
            "completed_count": sum(target.completed for target in targets),
            "editable": tutor_reviewable(round_obj),
            "has_questions": tutor_review_questions(round_obj).exists(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def tutor_review_form(request, round_id, participant_id):
    _require_operations(request.user)
    round_obj = get_object_or_404(EvaluationRound, pk=round_id)
    targets = tutor_review_targets(round_obj, request.user) if tutor_reviewable(round_obj) else []
    target = next((row for row in targets if row.pk == participant_id), None)
    if not target:
        raise PermissionDenied("평가할 수 없는 대상입니다.")
    existing = get_tutor_review(round_obj, request.user, participant_id)
    questions = list(tutor_review_questions(round_obj))
    initial = None
    if existing:
        initial = {
            f"question_{answer.question_id}": (
                answer.rating_value if answer.rating_value is not None else answer.text_value
            )
            for answer in existing.answers.all()
        }
    form = ReviewForm(request.POST or None, questions=questions, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            submit_tutor_review(
                round_obj=round_obj,
                tutor=request.user,
                participant_id=participant_id,
                answers=form.answer_values(),
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                "평가를 수정했습니다." if existing else "평가를 저장했습니다.",
            )
            return redirect("rounds:tutor-review-list", round_id=round_obj.pk)
    return render(
        request,
        "rounds/tutor_review_form.html",
        {
            "round_obj": round_obj,
            "target": target,
            "form": form,
            "questions": questions,
            "existing": existing,
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

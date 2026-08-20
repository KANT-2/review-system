from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import User
from accounts.permissions import is_operations_user
from notices.services import active_notices
from notifications.models import Notification
from notifications.services import notify_users
from reviews.forms import ReviewForm
from reviews.models import TutorReview
from reviews.services import (
    get_tutor_review,
    get_tutor_team_review,
    submit_tutor_review,
    submit_tutor_team_review,
    tutor_review_progress,
    tutor_review_questions,
    tutor_review_targets,
    tutor_reviewable,
    tutor_team_review_questions,
    tutor_team_review_targets,
)
from rounds.forms import EvaluationRoundForm, QuestionTemplateForm, TemplateQuestionFormSet
from rounds.models import EvaluationRound, QuestionTemplate
from rounds.services import (
    archive_question_template,
    complete_round,
    copy_question_template,
    delete_question_template,
    delete_round,
    get_review_progress,
    participant_progress_rows,
    pending_participant_rows,
    question_template_rows,
    reopen_round,
    restore_question_template,
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
    tutor_progress = tutor_review_progress(current, request.user) if current else None
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
            "tutor_progress": tutor_progress,
            "pending_approvals": pending_approvals,
            "active_notices": active_notices(),
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


@login_required
def publish_entry(request):
    """사이드바 '공개 설정' - 가장 최근 완료 회차의 공개 설정 화면으로 바로 이동한다."""
    _require_operations(request.user)
    latest_completed = (
        EvaluationRound.objects.filter(status=EvaluationRound.Status.COMPLETED)
        .order_by("-completed_at")
        .first()
    )
    if not latest_completed:
        messages.info(
            request,
            "아직 완료된 회차가 없어 공개 설정을 할 수 없습니다. 회차를 마감한 뒤 다시 시도해 주세요.",
        )
        return redirect("rounds:list")
    return redirect("rounds:publish-settings", round_id=latest_completed.pk)


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
            "participant_rows": participant_progress_rows(round_obj),
            "tutor_review_count": TutorReview.objects.filter(
                round=round_obj, evaluator=request.user
            ).count(),
            "start_blocking": [check.message for check in start_checks if not check.confirmable],
            "start_confirmable": [check.message for check in start_checks if check.confirmable],
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
def tutor_team_review_list(request, round_id):
    """튜터 팀평가 - 회차 팀 목록에서 한 팀씩 평가한다. tutor_review_list의 팀 단위 버전."""
    _require_operations(request.user)
    round_obj = get_object_or_404(EvaluationRound, pk=round_id)
    targets = (
        tutor_team_review_targets(round_obj, request.user) if tutor_reviewable(round_obj) else []
    )
    return render(
        request,
        "rounds/tutor_team_review_list.html",
        {
            "round_obj": round_obj,
            "targets": targets,
            "completed_count": sum(target.completed for target in targets),
            "editable": tutor_reviewable(round_obj),
            "has_questions": tutor_team_review_questions(round_obj).exists(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def tutor_team_review_form(request, round_id, team_id):
    _require_operations(request.user)
    round_obj = get_object_or_404(EvaluationRound, pk=round_id)
    targets = (
        tutor_team_review_targets(round_obj, request.user) if tutor_reviewable(round_obj) else []
    )
    target = next((row for row in targets if row.pk == team_id), None)
    if not target:
        raise PermissionDenied("평가할 수 없는 대상입니다.")
    existing = get_tutor_team_review(round_obj, request.user, team_id)
    questions = list(tutor_team_review_questions(round_obj))
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
            submit_tutor_team_review(
                round_obj=round_obj,
                tutor=request.user,
                team_id=team_id,
                answers=form.answer_values(),
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                "평가를 수정했습니다." if existing else "평가를 저장했습니다.",
            )
            return redirect("rounds:tutor-team-review-list", round_id=round_obj.pk)
    return render(
        request,
        "rounds/tutor_team_review_form.html",
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
    """문항 템플릿 목록 - 운영자가 admin 없이 평가 문항을 관리하는 화면.

    "전체" 탭은 보관된 템플릿도 맨 아래에 같이 보여주고(존재는 알 수 있어야 하니까),
    "보관됨" 탭은 보관된 것만 추린다.
    """
    _require_operations(request.user)
    archived_only = request.GET.get("view") == "archived"
    all_rows = question_template_rows()
    archived_count = sum(1 for row in all_rows if row.is_archived)
    return render(
        request,
        "rounds/template_list.html",
        {
            "templates": [row for row in all_rows if row.is_archived]
            if archived_only
            else all_rows,
            "archived_only": archived_only,
            "total_count": len(all_rows),
            "archived_count": archived_count,
        },
    )


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


@login_required
@require_POST
def template_archive(request, template_id):
    _require_operations(request.user)
    try:
        archive_question_template(template_id=template_id, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "템플릿을 보관했습니다. 목록·새 회차 선택지에서 빠집니다.")
    return redirect("rounds:template-list")


@login_required
@require_POST
def template_restore(request, template_id):
    _require_operations(request.user)
    restore_question_template(template_id=template_id, actor=request.user)
    messages.success(request, "템플릿을 복원했습니다.")
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
    """특정 회차 미제출 수강생들에게 제출 안내 메일을 발송합니다."""
    _require_operations(request.user)
    round_obj = get_object_or_404(EvaluationRound, pk=round_id)
    if round_obj.status != EvaluationRound.Status.IN_PROGRESS:
        messages.error(request, "진행 중인 회차만 제출 안내 메일을 보낼 수 있습니다.")
        return redirect("rounds:reviews", round_id=round_id)

    from accounts.email_services import send_submission_reminder_email

    pending_students = []
    sent_count = 0
    for row in pending_participant_rows(round_obj):
        student = row["participant"].user
        if not student.is_active:
            continue
        pending_students.append(student)
        if not student.email:
            continue
        name = student.first_name if student.first_name else student.email
        send_submission_reminder_email(round_obj, name, student.email)
        sent_count += 1

    notify_users(
        pending_students,
        category=Notification.Category.SUBMISSION_REMINDER,
        title="아직 제출하지 않은 평가가 있습니다",
        message=f"'{round_obj.title}' 회차의 팀·개인 평가를 확인해 주세요.",
        link=reverse("reviews:home"),
    )

    messages.success(
        request, f"총 {sent_count}명의 미제출 수강생에게 제출 안내 이메일이 발송되었습니다."
    )
    return redirect("rounds:reviews", round_id=round_id)

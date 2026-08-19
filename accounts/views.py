import csv
import io
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.forms import (
    LoginForm,
    OnboardingForm,
    PasswordChangeForm,
    SignUpForm,
    WhitelistEntryForm,
    clean_profile_image,
)
from accounts.models import EmailVerificationCode, ScheduledEmail, User
from accounts.portal import (
    build_student_portal,
    build_student_result_portal,
    round_result_csv_rows,
)
from accounts.services import (
    AccountConflictError,
    InvalidAccountTransition,
    RateLimitExceeded,
    account_rows,
    add_whitelist_emails,
    change_password,
    change_user_role,
    finalize_password_login,
    finish_password_reset,
    remove_whitelist_email,
    request_signup,
    require_password_rotation,
    revert_approval_to_pending,
    set_account_active,
    start_password_reset,
    transition_approval,
    whitelist_rows,
)
from notices.services import active_notices
from results.application import (
    add_tutor_note,
    delete_all_tutor_notes,
    delete_tutor_note,
    tutor_notes_by_student,
)

GENERIC_SIGNUP_MESSAGE = "가입 신청을 접수했습니다. 승인 뒤 로그인할 수 있습니다."
GENERIC_RESET_FAILURE = "이메일과 연락처가 등록된 정보와 일치하지 않습니다."


def _safe_json(request):
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _is_tutor(user):
    return (
        user.is_active
        and user.approval_status == User.ApprovalStatus.APPROVED
        and user.role == User.Role.TUTOR
    )


def _can_manage_approvals(user):
    return _is_tutor(user) or user.is_application_admin


def _login_context(*, login_form=None, signup_form=None, open_signup_modal=False):
    return {
        "form": login_form or LoginForm(),
        "signup_form": signup_form or SignUpForm(),
        "open_signup_modal": open_signup_modal,
        "google_enabled": settings.GOOGLE_OAUTH_ENABLED,
        "kakao_enabled": settings.KAKAO_OAUTH_ENABLED,
    }


@require_GET
def home_view(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if request.user.role in {User.Role.TUTOR, User.Role.ADMIN}:
        return redirect("rounds:dashboard")
    return redirect("accounts:dashboard")


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        if request.user.role in {User.Role.TUTOR, User.Role.ADMIN}:
            return redirect("rounds:dashboard")
        return redirect("accounts:dashboard")

    form = LoginForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        try:
            user = finalize_password_login(
                request,
                form.get_user(),
                remember_session=request.POST.get("remember_session") == "on",
            )
        except PermissionDenied:
            messages.error(request, "계정 승인 상태를 확인해 주세요.")
        else:
            if user.must_rotate_password:
                return redirect("accounts:password_change")
            if user.role in {User.Role.TUTOR, User.Role.ADMIN}:
                return redirect("rounds:dashboard")
            return redirect("accounts:dashboard")

    return render(
        request,
        "accounts/login.html",
        _login_context(
            login_form=form,
            open_signup_modal=request.GET.get("signup") == "1",
        ),
    )


@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.method == "GET":
        return redirect(f"{reverse('accounts:login')}?signup=1")

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            request_signup(
                request=request,
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )
        except RateLimitExceeded as error:
            response = render(
                request,
                "accounts/login.html",
                _login_context(signup_form=form, open_signup_modal=True),
                status=429,
            )
            response["Retry-After"] = str(error.retry_after)
            return response
        messages.success(request, GENERIC_SIGNUP_MESSAGE)
        return redirect("accounts:login")
    return render(
        request,
        "accounts/login.html",
        _login_context(signup_form=form, open_signup_modal=True),
    )


@require_POST
def password_reset_verify_api(request):
    """재설정 1단계 - 이메일과 연락처가 맞으면 세션에 확인 흔적만 남긴다."""
    data = _safe_json(request)
    if data is None:
        return JsonResponse({"success": False, "message": "잘못된 요청입니다."}, status=400)
    try:
        verified = start_password_reset(
            request=request,
            email=str(data.get("email", "")),
            phone_number=str(data.get("phone_number", "")),
        )
    except RateLimitExceeded as error:
        response = JsonResponse(
            {"success": False, "message": "시도가 너무 잦습니다. 잠시 후 다시 시도해 주세요."},
            status=429,
        )
        response["Retry-After"] = str(error.retry_after)
        return response
    if not verified:
        return JsonResponse({"success": False, "message": GENERIC_RESET_FAILURE}, status=400)
    return JsonResponse({"success": True, "message": "본인 확인이 완료되었습니다."})


@require_POST
def password_reset_api(request):
    """재설정 2단계 - 대상 계정은 세션의 확인 흔적에서만 읽는다(요청 본문에서 받지 않는다)."""
    data = _safe_json(request)
    if data is None:
        return JsonResponse({"success": False, "message": "잘못된 요청입니다."}, status=400)
    try:
        finish_password_reset(request=request, new_password=str(data.get("new_password", "")))
    except AccountConflictError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    except ValidationError as error:
        return JsonResponse({"success": False, "message": " ".join(error.messages)}, status=400)
    return JsonResponse({"success": True, "message": "비밀번호를 변경했습니다. 로그인해 주세요."})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("accounts:login")


def _needs_onboarding(user):
    """수강생은 필수 프로필(이름·기수·연락처)을 채우기 전에는 평가 화면을 쓸 수 없다.

    가입 신청 때는 계정 정보만 받으므로(SignUpForm), 승인 뒤 본인이 직접 채운다. 소셜 가입도
    같은 경로를 지난다. 화면에서 가리는 것만으로는 막을 수 없어 서버에서 되돌려 보낸다.
    """
    return user.role == User.Role.STUDENT and not user.is_onboarded


@login_required
@require_http_methods(["GET", "POST"])
def onboarding_view(request):
    if not _needs_onboarding(request.user):
        return redirect("accounts:dashboard")
    form = OnboardingForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.is_onboarded = True
        user.save(update_fields=["first_name", "session_info", "phone_number", "is_onboarded"])
        messages.success(request, "프로필 등록이 완료되었습니다. 이제 평가에 참여할 수 있습니다.")
        return redirect("accounts:dashboard")
    return render(request, "accounts/onboarding.html", {"form": form})


@login_required
def dashboard_view(request):
    if request.user.role in {User.Role.TUTOR, User.Role.ADMIN}:
        return redirect("rounds:dashboard")
    if _needs_onboarding(request.user):
        return redirect("accounts:onboarding")
    return render(
        request,
        "accounts/dashboard.html",
        {
            "portal": build_student_portal(request.user),
            "active_notices": active_notices(),
        },
    )


@login_required
def mypage_view(request):
    """마이페이지 - 학생은 프로필과 공개된 결과를, 튜터·관리자는 계정 설정만 본다."""
    if _needs_onboarding(request.user):
        return redirect("accounts:onboarding")
    is_student = request.user.role == User.Role.STUDENT
    requested = request.GET.get("round")
    selected_round_id = int(requested) if requested and requested.isdigit() else None
    portal = (
        build_student_result_portal(request.user, selected_round_id=selected_round_id)
        if is_student
        else None
    )
    return render(
        request,
        "accounts/mypage.html",
        {"portal": portal, "is_student": is_student},
    )


@login_required
@require_GET
def mypage_round_result_csv(request, round_id):
    """마이페이지에서 고른 회차의 결과 CSV 다운로드(MVP 의도적 확장 - CONTEXT.md 참고)."""
    payload = round_result_csv_rows(request.user, round_id)
    if payload is None:
        raise Http404
    buffer = io.StringIO()
    csv.writer(buffer).writerows(payload["rows"])
    # BOM은 한 번만 - 응답에 바로 writer.writerows를 걸면 write() 호출마다 BOM이 반복된다.
    response = HttpResponse(
        buffer.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
    )
    filename = f"{payload['round_name']}_결과.csv".replace(" ", "_")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_POST
def whitelist_add(request):
    """수강생 관리 화면의 명단 등록 - 화이트리스트에 이메일을 추가한다.

    여기에 등록된 이메일로 가입하면 이메일 확인만으로 자동 승인된다 - 운영자가 미리 명단을
    넣어두면 한 명씩 승인할 필요가 없다.
    """
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    form = WhitelistEntryForm(request.POST)
    if not form.is_valid():
        messages.error(request, next(iter(form.errors.values()))[0])
        return redirect("accounts:account_admin")
    added, updated = add_whitelist_emails(
        emails=form.cleaned_data["emails"],
        session_info=form.cleaned_data["session_info"],
        actor=request.user,
    )
    parts = []
    if added:
        parts.append(f"{len(added)}건 등록")
    if updated:
        parts.append(f"{len(updated)}건 기수 갱신")
    messages.success(request, f"명단을 {', '.join(parts)}했습니다.")
    return redirect("accounts:account_admin")


@login_required
@require_POST
def whitelist_delete(request, entry_id):
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    try:
        entry = remove_whitelist_email(entry_id=entry_id, actor=request.user)
    except InvalidAccountTransition as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"{entry.email}을 명단에서 지웠습니다.")
    return redirect("accounts:account_admin")


ACCOUNT_ADMIN_VISIBLE_ROW_COUNT = 8


@login_required
def account_admin(request):
    """수강생 관리 - 승인 대기, 사전 등록 명단, 전체 계정을 한 화면에서 다룬다."""
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    role = request.GET.get("role") or ""
    status = request.GET.get("status") or ""
    query = (request.GET.get("q") or "").strip()
    if role not in dict(User.Role.choices):
        role = ""
    if status not in dict(User.ApprovalStatus.choices):
        status = ""
    from rounds.models import EvaluationRound
    from teams.models import Team

    current_round = (
        EvaluationRound.objects.filter(status=EvaluationRound.Status.IN_PROGRESS)
        .order_by("-id")
        .first()
        or EvaluationRound.objects.order_by("-id").first()
    )
    if current_round:
        teams = list(
            Team.objects.filter(round=current_round)
            .prefetch_related("memberships")
            .order_by("team_number")
        )
        current_round_title = current_round.title
    else:
        teams = []
        current_round_title = ""
    scheduled_emails = ScheduledEmail.objects.filter(status=ScheduledEmail.Status.PENDING).order_by(
        "scheduled_at"
    )

    pending_users = list(
        User.objects.filter(
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.PENDING,
        ).order_by("-date_joined")
    )
    accounts = list(account_rows(role=role, status=status, query=query))
    return render(
        request,
        "accounts/account_admin.html",
        {
            "teams": teams,
            "current_round_title": current_round_title,
            "scheduled_emails": scheduled_emails,
            "notes": tutor_notes_by_student(),
            "pending_users": pending_users,
            "pending_head": pending_users[:ACCOUNT_ADMIN_VISIBLE_ROW_COUNT],
            "pending_rest": pending_users[ACCOUNT_ADMIN_VISIBLE_ROW_COUNT:],
            "whitelist_form": WhitelistEntryForm(),
            "whitelist_entries": whitelist_rows(),
            "accounts": accounts,
            "accounts_head": accounts[:ACCOUNT_ADMIN_VISIBLE_ROW_COUNT],
            "accounts_rest": accounts[ACCOUNT_ADMIN_VISIBLE_ROW_COUNT:],
            "selected_role": role,
            "selected_status": status,
            "query": query,
            "role_choices": User.Role.choices,
            "status_choices": User.ApprovalStatus.choices,
            "can_change_role": request.user.is_application_admin,
        },
    )


@login_required
@require_POST
def account_action(request, user_id, action):
    """계정 관리 화면의 한 줄 동작 - 되돌리기·역할 변경·활성 전환·비밀번호 재설정 요구."""
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    handlers = {
        "revert-approval": lambda: revert_approval_to_pending(
            actor=request.user, target_id=user_id
        ),
        "activate": lambda: set_account_active(
            actor=request.user, target_id=user_id, is_active=True
        ),
        "deactivate": lambda: set_account_active(
            actor=request.user, target_id=user_id, is_active=False
        ),
        "require-password-reset": lambda: require_password_rotation(
            actor=request.user, target_id=user_id
        ),
        "make-tutor": lambda: change_user_role(
            actor=request.user, target_id=user_id, role=User.Role.TUTOR
        ),
        "make-student": lambda: change_user_role(
            actor=request.user, target_id=user_id, role=User.Role.STUDENT
        ),
    }
    messages_by_action = {
        "revert-approval": "승인 대기로 되돌렸습니다.",
        "activate": "계정을 다시 활성화했습니다.",
        "deactivate": "계정을 비활성화했습니다. 기존 로그인 세션도 끊겼습니다.",
        "require-password-reset": "다음 로그인에서 비밀번호를 새로 정하도록 했습니다.",
        "make-tutor": "튜터로 역할을 바꿨습니다.",
        "make-student": "수강생으로 역할을 바꿨습니다.",
    }
    handler = handlers.get(action)
    if handler is None:
        messages.error(request, "지원하지 않는 동작입니다.")
        return redirect("accounts:account_admin")
    try:
        handler()
    except PermissionDenied:
        messages.error(request, "이 계정에 대한 권한이 없습니다.")
    except (InvalidAccountTransition, User.DoesNotExist) as error:
        messages.error(request, str(error) or "상태가 맞지 않아 처리하지 못했습니다.")
    else:
        messages.success(request, messages_by_action[action])
    return redirect("accounts:account_admin")


@login_required
@require_POST
def save_student_note(request, user_id):
    """수강생별 튜터 전용 메모를 기록에 추가한다. 학생 화면에는 어떤 경로로도 노출되지 않는다."""
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    try:
        add_tutor_note(student_id=user_id, body=request.POST.get("body", ""), actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "메모를 남겼습니다.")
    return redirect("accounts:account_admin")


@login_required
@require_POST
def delete_student_note(request, user_id, note_id):
    """메모 기록 한 건 삭제."""
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    try:
        delete_tutor_note(student_id=user_id, note_id=note_id, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "메모를 지웠습니다.")
    return redirect("accounts:account_admin")


@login_required
@require_POST
def delete_all_student_notes(request, user_id):
    """수강생 한 명의 메모 기록 전체 삭제."""
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    try:
        delete_all_tutor_notes(student_id=user_id, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "메모 기록을 모두 지웠습니다.")
    return redirect("accounts:account_admin")


BULK_APPROVAL_DECISIONS = {
    "approve": User.ApprovalStatus.APPROVED,
    "reject": User.ApprovalStatus.REJECTED,
}


@login_required
@require_POST
def bulk_approval(request):
    """승인 대기 목록에서 체크한 계정을 한 번에 승인하거나 반려한다.

    화면에서 확인창을 띄우더라도 서버에서 권한과 상태를 다시 확인한다 - 직접 POST를 보내는
    경로가 남아 있기 때문이다.
    """
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    decision = BULK_APPROVAL_DECISIONS.get(request.POST.get("decision"))
    if decision is None:
        messages.error(request, "지원하지 않는 동작입니다.")
        return redirect("accounts:account_admin")
    user_ids = [value for value in request.POST.getlist("user_ids") if value.isdigit()]
    if not user_ids:
        messages.error(request, "처리할 계정을 한 명 이상 선택해 주세요.")
        return redirect("accounts:account_admin")
    changed = 0
    skipped = 0
    for user_id in user_ids:
        try:
            transition_approval(actor=request.user, target_id=int(user_id), decision=decision)
        except PermissionDenied:
            raise
        except (InvalidAccountTransition, User.DoesNotExist):
            skipped += 1
        else:
            changed += 1
    label = "승인" if decision == User.ApprovalStatus.APPROVED else "반려"
    if changed:
        messages.success(request, f"{changed}명을 {label}했습니다.")
    if skipped:
        messages.error(request, f"{skipped}명은 이미 처리되었거나 상태가 맞지 않아 건너뛰었습니다.")
    return redirect("accounts:account_admin")


def _html_transition(request, user_id, decision):
    try:
        target = transition_approval(actor=request.user, target_id=user_id, decision=decision)
    except PermissionDenied:
        raise
    except (InvalidAccountTransition, User.DoesNotExist):
        messages.error(request, "이미 처리되었거나 승인할 수 없는 계정입니다.")
    else:
        messages.success(request, f"{target.email} 계정 상태를 변경했습니다.")
    return redirect("accounts:account_admin")


@login_required
@require_POST
def approve_user(request, user_id):
    return _html_transition(request, user_id, User.ApprovalStatus.APPROVED)


@login_required
@require_POST
def reject_user(request, user_id):
    return _html_transition(request, user_id, User.ApprovalStatus.REJECTED)


@login_required
@require_POST
def api_onboarding(request):
    data = _safe_json(request)
    if data is None:
        return JsonResponse({"success": False, "message": "잘못된 JSON 요청입니다."}, status=400)
    fields = {
        key: str(data.get(key, "")).strip()
        for key in ("first_name", "session_info", "phone_number")
    }
    if (
        not all(fields.values())
        or len(fields["first_name"]) > 150
        or len(fields["session_info"]) > 50
        or len(fields["phone_number"]) > 20
    ):
        return JsonResponse({"success": False, "message": "입력값을 확인해 주세요."}, status=400)
    for key, value in fields.items():
        setattr(request.user, key, value)
    request.user.is_onboarded = True
    request.user.save()
    return JsonResponse({"success": True, "message": "온보딩이 완료되었습니다."})


TRUE_VALUES = {"1", "true", "on", "yes"}


@require_POST
def update_profile_api(request):
    # login_required의 기본 동작(로그인 페이지로 302 리다이렉트)은 fetch가
    # 응답을 그대로 HTML로 받게 만들어 JSON 파싱이 깨진다. 세션 만료 시에도
    # 이 API는 JSON으로 응답해야 하므로 여기서 직접 인증 여부를 확인한다.
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "message": "다시 로그인해 주세요."}, status=401
        )
    # request.body는 multipart 업로드에서도 전체 페이로드를 메모리로 읽어
    # DATA_UPLOAD_MAX_MEMORY_SIZE 검사에 걸리게 만든다. 파일이 함께 오는
    # multipart 요청에서는 request.body를 건드리지 않고 request.POST를 쓴다.
    if request.content_type == "application/json":
        data = _safe_json(request)
        if data is None:
            return JsonResponse(
                {"success": False, "message": "잘못된 JSON 요청입니다."}, status=400
            )
    else:
        data = request.POST.dict()
    allowed = {"first_name": 150, "phone_number": 20, "session_info": 50}
    for field, max_length in allowed.items():
        if field in data:
            value = str(data[field]).strip()
            if len(value) > max_length:
                return JsonResponse(
                    {"success": False, "message": "입력값이 너무 깁니다."}, status=400
                )
            setattr(request.user, field, value)
    # 프로필 사진은 multipart 요청에서만 온다 - JSON으로 프로필만 고치는 기존 경로는 그대로다.
    uploaded = request.FILES.get("profile_image")
    if uploaded is not None:
        try:
            request.user.profile_image = clean_profile_image(uploaded)
        except ValidationError as error:
            return JsonResponse({"success": False, "message": error.messages[0]}, status=400)
    elif str(data.get("clear_profile_image", "")).lower() in TRUE_VALUES:
        request.user.profile_image = None
    request.user.save()
    return JsonResponse({"success": True, "message": "프로필이 수정되었습니다."})


@require_POST
def signup_api(request):
    data = _safe_json(request)
    if data is None or not data.get("email") or not data.get("password"):
        return JsonResponse({"success": False, "message": "잘못된 요청입니다."}, status=400)
    form = SignUpForm(
        {
            "email": data["email"],
            "password": data["password"],
            "password_confirm": data.get("password_confirm", data["password"]),
        }
    )
    if not form.is_valid():
        message = next(iter(form.errors.values()))[0]
        return JsonResponse({"success": False, "message": message}, status=400)
    try:
        request_signup(
            request=request,
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
    except RateLimitExceeded as error:
        response = JsonResponse({"success": True, "message": GENERIC_SIGNUP_MESSAGE}, status=429)
        response["Retry-After"] = str(error.retry_after)
        return response
    return JsonResponse({"success": True, "message": GENERIC_SIGNUP_MESSAGE}, status=202)


def _api_transition(request, user_id, decision):
    try:
        target = transition_approval(actor=request.user, target_id=user_id, decision=decision)
    except PermissionDenied:
        return JsonResponse({"success": False, "message": "권한이 없습니다."}, status=403)
    except (InvalidAccountTransition, User.DoesNotExist):
        return JsonResponse({"success": False, "message": "상태가 충돌했습니다."}, status=409)
    return JsonResponse({"success": True, "message": f"{target.email} 계정 상태를 변경했습니다."})


@login_required
@require_POST
def approve_user_api(request, user_id):
    return _api_transition(request, user_id, User.ApprovalStatus.APPROVED)


@login_required
@require_POST
def reject_user_api(request, user_id):
    return _api_transition(request, user_id, User.ApprovalStatus.REJECTED)


@login_required
@require_http_methods(["GET", "POST"])
def password_change_view(request):
    if not request.user.has_usable_password():
        raise PermissionDenied
    form = PasswordChangeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            change_password(
                request=request,
                **{
                    "current_password": form.cleaned_data["current_password"],
                    "new_password": form.cleaned_data["new_password"],
                },
            )
        except RateLimitExceeded as error:
            response = render(request, "accounts/password_change.html", {"form": form}, status=429)
            response["Retry-After"] = str(error.retry_after)
            return response
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "비밀번호를 변경했습니다.")
            return redirect("accounts:mypage")
    return render(request, "accounts/password_change.html", {"form": form})


@require_POST
def api_send_email_code(request):
    """6자리 본인 인증 이메일 코드를 발송합니다."""
    data = _safe_json(request)
    if not data:
        return JsonResponse({"success": False, "message": "잘못된 요청입니다."}, status=400)

    email = data.get("email", "").strip()
    purpose = data.get("purpose", "").strip()

    if not email or "@" not in email:
        return JsonResponse(
            {"success": False, "message": "올바른 이메일 주소를 입력해 주세요."}, status=400
        )

    if purpose not in [
        EmailVerificationCode.Purpose.SIGNUP,
        EmailVerificationCode.Purpose.PASSWORD_RESET,
    ]:
        return JsonResponse(
            {"success": False, "message": "올바르지 않은 인증 목적입니다."}, status=400
        )

    if purpose == EmailVerificationCode.Purpose.PASSWORD_RESET:
        if not User.objects.filter(email=email).exists():
            return JsonResponse(
                {"success": False, "message": "등록되지 않은 이메일 주소입니다."}, status=404
            )

    try:
        from accounts.email_services import send_email_verification_code

        send_email_verification_code(email, purpose)
        return JsonResponse(
            {"success": True, "message": "6자리 인증코드가 이메일로 발송되었습니다. (유효시간 5분)"}
        )
    except Exception as error:
        return JsonResponse({"success": False, "message": f"이메일 발송 오류: {error}"}, status=500)


@require_POST
def api_verify_email_code(request):
    """입력한 6자리 이메일 인증코드를 검증합니다."""
    data = _safe_json(request)
    if not data:
        return JsonResponse({"success": False, "message": "잘못된 요청입니다."}, status=400)

    email = data.get("email", "").strip()
    code = data.get("code", "").strip()
    purpose = data.get("purpose", "").strip()

    if not email or not code:
        return JsonResponse(
            {"success": False, "message": "이메일과 6자리 인증코드를 모두 입력해 주세요."},
            status=400,
        )

    from accounts.email_services import verify_email_code

    success = verify_email_code(email, code, purpose)

    if success:
        return JsonResponse(
            {"success": True, "message": "이메일 본인 인증이 성공적으로 완료되었습니다."}
        )
    return JsonResponse(
        {"success": False, "message": "인증코드가 올바르지 않거나 5분 유효시간이 만료되었습니다."},
        status=400,
    )


@login_required
@require_POST
def send_tutor_announcement_view(request):
    """튜터/관리자가 선택된 수강생 개인들 또는 전체에게 공지/안내 이메일을 발송합니다."""
    if not (request.user.is_staff or request.user.role in [User.Role.TUTOR, User.Role.ADMIN]):
        raise PermissionDenied

    subject = request.POST.get("subject", "").strip()
    message = request.POST.get("message", "").strip()
    target_type = request.POST.get("send_target_type", "all").strip()
    target_user_id = request.POST.get("target_user_id", "").strip()
    target_team_id = request.POST.get("target_team_id", "").strip()
    selected_user_ids = request.POST.getlist("selected_user_ids")

    if not subject or not message:
        messages.error(request, "제목과 내용을 모두 입력해 주세요.")
        return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))
    if target_type not in {"all", "team", "select"}:
        messages.error(request, "올바른 발송 대상을 선택해 주세요.")
        return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))

    if target_type == "team":
        from teams.models import Team

        team = Team.objects.filter(id=target_team_id).first() if target_team_id else None
        if not team:
            messages.error(request, "발송할 조(팀)를 선택해 주세요.")
            return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))
        recipient_emails = list(
            team.memberships.filter(participant__user__is_active=True)
            .exclude(participant__user__email="")
            .values_list("participant__user__email", flat=True)
        )
        team_name = team.name
        target_info_str = f"'{team_name}' (총 {len(recipient_emails)}명)"
    elif target_type == "select":
        recipient_emails = list(
            User.objects.filter(
                id__in=selected_user_ids,
                role=User.Role.STUDENT,
                is_active=True,
            )
            .exclude(email="")
            .values_list("email", flat=True)
        )
        if not recipient_emails:
            messages.error(request, "발송할 수강생을 한 명 이상 선택해 주세요.")
            return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))
        target_info_str = f"선택한 수강생 (총 {len(recipient_emails)}명)"
    elif target_user_id:
        target_user = User.objects.filter(id=target_user_id).first()
        if target_user and target_user.role == User.Role.STUDENT and target_user.is_active:
            recipient_emails = [target_user.email]
            name = target_user.first_name or target_user.email
            target_info_str = f"수강생 {name}님"
        else:
            recipient_emails = []
            target_info_str = "선택한 수강생 (0명)"
    else:
        recipient_emails = list(
            User.objects.filter(role=User.Role.STUDENT, is_active=True)
            .exclude(email="")
            .values_list("email", flat=True)
        )
        target_info_str = f"전체 수강생 (총 {len(recipient_emails)}명)"

    send_type = request.POST.get("send_type", "now").strip()
    scheduled_at_str = request.POST.get("scheduled_at", "").strip()
    if send_type not in {"now", "scheduled"}:
        messages.error(request, "올바른 발송 시점을 선택해 주세요.")
        return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))

    if send_type == "scheduled":
        if not scheduled_at_str:
            messages.error(request, "예약 발송 일시를 입력해 주세요.")
            return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))
        try:
            import json

            from django.utils.dateparse import parse_datetime

            from accounts.models import ScheduledEmail

            scheduled_at = parse_datetime(scheduled_at_str)
            if scheduled_at and timezone.is_naive(scheduled_at):
                scheduled_at = timezone.make_aware(scheduled_at)

            if not scheduled_at or scheduled_at <= timezone.now():
                messages.error(request, "예약 발송 일시는 현재 시각 이후로 지정해 주세요.")
                return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))

            scheduled_target_type = ScheduledEmail.TargetType.ALL
            target_team_obj = None
            if target_type == "team":
                from teams.models import Team

                scheduled_target_type = ScheduledEmail.TargetType.TEAM
                target_team_obj = Team.objects.filter(id=target_team_id).first()
            elif target_type == "select":
                scheduled_target_type = ScheduledEmail.TargetType.SELECT
            elif target_user_id:
                scheduled_target_type = ScheduledEmail.TargetType.SINGLE

            ScheduledEmail.objects.create(
                sender=request.user,
                subject=subject,
                message=message,
                target_type=scheduled_target_type,
                target_team=target_team_obj,
                selected_user_ids_json=json.dumps(
                    selected_user_ids
                    if selected_user_ids
                    else ([target_user_id] if target_user_id else [])
                ),
                scheduled_at=scheduled_at,
                status=ScheduledEmail.Status.PENDING,
            )
            messages.success(
                request,
                f"{scheduled_at.strftime('%Y-%m-%d %H:%M')}에 {target_info_str} 대상으로 공지 메일을 예약했습니다.",
            )
            return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))
        except Exception as e:
            messages.error(request, f"예약 일시 처리 중 오류가 발생했습니다: {e}")
            return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))

    from accounts.email_services import send_tutor_announcement_email

    send_tutor_announcement_email(subject, message, recipient_emails)
    messages.success(request, f"{target_info_str}에게 공지 메일을 발송했습니다.")
    return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))


@login_required
@require_POST
def cancel_scheduled_email_view(request, email_id):
    """예약된 공지 이메일을 발송 취소합니다."""
    if not (request.user.is_staff or request.user.role in [User.Role.TUTOR, User.Role.ADMIN]):
        raise PermissionDenied

    from accounts.models import ScheduledEmail

    scheduled_item = get_object_or_404(ScheduledEmail, pk=email_id)
    if scheduled_item.status == ScheduledEmail.Status.PENDING:
        scheduled_item.status = ScheduledEmail.Status.CANCELLED
        scheduled_item.save(update_fields=["status"])
        messages.success(request, f"'{scheduled_item.subject}' 예약 공지가 취소되었습니다.")
    else:
        messages.error(request, "이미 처리되었거나 취소할 수 없는 예약 건입니다.")

    return redirect(request.META.get("HTTP_REFERER", "accounts:account_admin"))

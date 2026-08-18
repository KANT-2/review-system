import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.forms import (
    LoginForm,
    OnboardingForm,
    PasswordChangeForm,
    SignUpForm,
    WhitelistEntryForm,
)
from accounts.models import User, WhitelistEmail
from accounts.portal import build_student_portal, build_student_result_portal
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
    update_account_profile,
    whitelist_rows,
)
from rounds.models import EvaluationRound, RoundParticipant

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

    portal = build_student_portal(request.user)

    latest_completed = (
        RoundParticipant.objects
        .select_related("round")
        .filter(
            user=request.user,
            round__status=EvaluationRound.Status.COMPLETED,
        )
        .order_by("-round__started_at", "-round_id")
        .first()
    )


    return render(
        request,
        "accounts/dashboard.html",
        { 
            "portal": portal,
          "latest_completed": latest_completed,
        },
    )


@login_required
def mypage_view(request):
    if _needs_onboarding(request.user):
        return redirect("accounts:onboarding")
    return render(
        request,
        "accounts/mypage.html",
        {"portal": build_student_result_portal(request.user)},
    )


@login_required
def tutor_dashboard(request):
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    pending_users = User.objects.filter(
        role=User.Role.STUDENT,
        approval_status=User.ApprovalStatus.PENDING,
    ).order_by("-date_joined")
    return render(
        request,
        "accounts/tutor_dashboard.html",
        {
            "pending_users": pending_users,
            "approved_students_count": User.objects.filter(
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
            ).count(),
            "whitelist_count": WhitelistEmail.objects.count(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def whitelist_view(request):
    """수강생 명단(화이트리스트) 관리.

    여기에 등록된 이메일로 가입하면 이메일 확인만으로 자동 승인된다 - 운영자가 미리 명단을
    넣어두면 한 명씩 승인할 필요가 없다.
    """
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    form = WhitelistEntryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
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
        return redirect("accounts:whitelist")
    return render(
        request,
        "accounts/whitelist.html",
        {"form": form, "entries": whitelist_rows()},
    )


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
    return redirect("accounts:whitelist")


@login_required
def account_admin(request):
    """계정 관리 - 승인 상태·활성 여부·역할을 화면에서 다룬다."""
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    role = request.GET.get("role") or ""
    status = request.GET.get("status") or ""
    query = (request.GET.get("q") or "").strip()
    if role not in dict(User.Role.choices):
        role = ""
    if status not in dict(User.ApprovalStatus.choices):
        status = ""
    return render(
        request,
        "accounts/account_admin.html",
        {
            "accounts": account_rows(role=role, status=status, query=query),
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
def account_profile_update(request, user_id):
    """계정 관리 화면의 이름·식별번호·기수 수정(ACC-001)."""
    if not _can_manage_approvals(request.user):
        raise PermissionDenied
    try:
        update_account_profile(
            actor=request.user,
            target_id=user_id,
            first_name=request.POST.get("first_name", ""),
            student_number=request.POST.get("student_number", ""),
            session_info=request.POST.get("session_info", ""),
        )
    except PermissionDenied:
        messages.error(request, "이 계정에 대한 권한이 없습니다.")
    except (InvalidAccountTransition, User.DoesNotExist) as error:
        messages.error(request, str(error) or "계정 정보를 저장하지 못했습니다.")
    else:
        messages.success(request, "계정 정보를 저장했습니다.")
    return redirect("accounts:account_admin")


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


def _html_transition(request, user_id, decision):
    try:
        target = transition_approval(actor=request.user, target_id=user_id, decision=decision)
    except PermissionDenied:
        raise
    except (InvalidAccountTransition, User.DoesNotExist):
        messages.error(request, "이미 처리되었거나 승인할 수 없는 계정입니다.")
    else:
        messages.success(request, f"{target.email} 계정 상태를 변경했습니다.")
    return redirect("accounts:tutor_dashboard")


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


@login_required
@require_POST
def update_profile_api(request):
    data = _safe_json(request)
    if data is None:
        if request.content_type == "application/json":
            return JsonResponse(
                {"success": False, "message": "잘못된 JSON 요청입니다."}, status=400
            )
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

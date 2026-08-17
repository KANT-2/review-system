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
    ConfirmationPasswordForm,
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
    add_whitelist_emails,
    change_password,
    confirm_email_ownership,
    finalize_password_login,
    get_confirmation_address,
    remove_whitelist_email,
    request_signup,
    resend_confirmation,
    store_confirmation_grant,
    transition_approval,
    whitelist_rows,
)

GENERIC_SIGNUP_MESSAGE = "요청을 접수했습니다. 해당 주소로 보낸 안내를 확인해 주세요."


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
            messages.error(request, "이메일 확인과 계정 승인 상태를 확인해 주세요.")
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
            request_signup(request=request, **form.cleaned_data)
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


@require_GET
def email_confirm_key(request, key):
    store_confirmation_grant(request, key)
    return redirect("accounts:email_confirm")


@require_http_methods(["GET", "POST"])
def email_confirm(request):
    address = get_confirmation_address(request)
    needs_password = bool(address and not address.user.has_usable_password())
    form = ConfirmationPasswordForm(request.POST or None) if needs_password else None
    if request.method == "POST":
        if needs_password and not form.is_valid():
            return render(
                request,
                "accounts/email_confirm.html",
                {"address": address, "form": form, "needs_password": True},
            )
        try:
            user = confirm_email_ownership(
                request,
                password=form.cleaned_data["password"] if needs_password else None,
            )
        except (AccountConflictError, ValidationError):
            messages.error(request, "확인 요청이 만료되었거나 이미 처리되었습니다.")
        else:
            if user.approval_status == User.ApprovalStatus.APPROVED:
                messages.success(request, "이메일 확인과 계정 승인이 완료되었습니다.")
            else:
                messages.success(request, "이메일 확인이 완료되었습니다. 승인을 기다려주세요.")
        return redirect("accounts:login")
    return render(
        request,
        "accounts/email_confirm.html",
        {"address": address, "form": form, "needs_password": needs_password},
    )


@require_POST
def email_resend(request):
    email = request.POST.get("email", "")
    try:
        resend_confirmation(request=request, email=email)
    except RateLimitExceeded as error:
        response = JsonResponse({"success": True, "message": GENERIC_SIGNUP_MESSAGE}, status=429)
        response["Retry-After"] = str(error.retry_after)
        return response
    return JsonResponse({"success": True, "message": GENERIC_SIGNUP_MESSAGE})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("accounts:login")


def _needs_onboarding(user):
    """수강생은 필수 프로필(이름·기수·연락처)을 채우기 전에는 평가 화면을 쓸 수 없다.

    가입 신청 때는 이메일만 받으므로(SignUpForm), 승인 뒤 본인이 직접 채운다. 소셜 가입도
    같은 경로를 지난다.
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
        {"portal": build_student_portal(request.user)},
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
        emailaddress__verified=True,
        emailaddress__primary=True,
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
    if data is None or not data.get("email"):
        return JsonResponse({"success": False, "message": "잘못된 요청입니다."}, status=400)
    try:
        request_signup(request=request, email=data["email"])
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

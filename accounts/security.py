from django.conf import settings
from django.shortcuts import render

from accounts.forms import LoginForm, SignUpForm
from accounts.models import canonicalize_email


def canonicalize_axes_username(request, credentials):
    value = credentials.get("username") or credentials.get("email") or ""
    return canonicalize_email(value)


def get_direct_client_ip(request):
    return request.META.get("REMOTE_ADDR")


def axes_lockout_response(request, response, credentials, *args, **kwargs):
    # 비밀번호를 넘기지 않아 인증을 다시 시도하지 않으면서, 일반 로그인 실패와 같은
    # non-field error 위치에 잠금 안내를 표시한다.
    form = LoginForm(
        {"email": canonicalize_axes_username(request, credentials)},
        request=request,
    )
    form.is_valid()
    form.errors.clear()
    form.add_error(None, "로그인 시도가 너무 많습니다. 15분 후 다시 시도해 주세요.")
    response = render(
        request,
        "accounts/login.html",
        {
            "form": form,
            "signup_form": SignUpForm(),
            "open_signup_modal": False,
            "google_enabled": settings.GOOGLE_OAUTH_ENABLED,
            "kakao_enabled": settings.KAKAO_OAUTH_ENABLED,
        },
        status=429,
    )
    response["Retry-After"] = "900"
    return response

from django.http import JsonResponse

from accounts.models import canonicalize_email


def canonicalize_axes_username(request, credentials):
    value = credentials.get("username") or credentials.get("email") or ""
    return canonicalize_email(value)


def get_direct_client_ip(request):
    return request.META.get("REMOTE_ADDR")


def axes_lockout_response(request, credentials, *args, **kwargs):
    response = JsonResponse(
        {"success": False, "message": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요."},
        status=429,
    )
    response["Retry-After"] = "900"
    return response

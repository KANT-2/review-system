import ipaddress
import uuid

from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse


class TrustedProxyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        request.request_id = uuid.uuid4().hex
        forwarded_headers = ("HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_PROTO")
        remote_address = request.META.get("REMOTE_ADDR", "")
        is_trusted = settings.TRUST_PROXY_HEADERS and self._is_trusted(
            remote_address, settings.TRUSTED_PROXY_IPS
        )
        if is_trusted:
            forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
            addresses = [item.strip() for item in forwarded_for.split(",") if item.strip()]
            if len(addresses) >= settings.TRUSTED_PROXY_HOPS:
                request.META["REMOTE_ADDR"] = addresses[-settings.TRUSTED_PROXY_HOPS]
            if request.META.get("HTTP_X_FORWARDED_PROTO") == "https":
                request.META["wsgi.url_scheme"] = "https"
        else:
            for header in forwarded_headers:
                request.META.pop(header, None)
        return self.get_response(request)

    @staticmethod
    def _is_trusted(remote_address, networks):
        try:
            address = ipaddress.ip_address(remote_address)
            return any(address in ipaddress.ip_network(network) for network in networks)
        except ValueError:
            return False


class AccountAccessMiddleware:
    ALLOWED_WHILE_RESTRICTED = {
        "accounts:login",
        "accounts:logout",
        "accounts:email_confirm",
        "accounts:email_confirm_key",
        "accounts:email_resend",
        "accounts:password_change",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        try:
            view_name = resolve(request.path_info).view_name
        except Resolver404:
            view_name = ""
        user = request.user
        session_version = request.session.get("auth_session_version")
        version_matches = session_version == user.auth_session_version
        has_access = user.is_active and user.approval_status == user.ApprovalStatus.APPROVED

        if not has_access or not version_matches:
            logout(request)
            return redirect(reverse("accounts:login"))

        if user.must_rotate_password and view_name not in self.ALLOWED_WHILE_RESTRICTED:
            return redirect(reverse("accounts:password_change"))

        return self.get_response(request)

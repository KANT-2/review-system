import secrets
import time
from urllib.parse import urlencode

from allauth.socialaccount.providers.google import views as google_views
from allauth.socialaccount.providers.kakao import views as kakao_views
from django.conf import settings
from django.http import Http404, HttpResponseBadRequest
from django.views.decorators.http import require_POST

OAUTH_TTL_SECONDS = 300


def _require_provider(enabled):
    if not enabled:
        raise Http404("Social login provider is not configured")


@require_POST
def google_login(request):
    _require_provider(settings.GOOGLE_OAUTH_ENABLED)
    nonce = secrets.token_urlsafe(32)
    nonces = request.session.get("google_oidc_nonces", {})
    now = time.time()
    nonces = {key: value for key, value in nonces.items() if now - value <= OAUTH_TTL_SECONDS}
    nonces[nonce] = now
    request.session["google_oidc_nonces"] = nonces
    query = request.GET.copy()
    query["auth_params"] = urlencode({"nonce": nonce})
    request.GET = query
    return google_views.oauth2_login(request)


def _valid_state_age(request):
    state_id = request.GET.get("state")
    state_entry = (request.session.get("socialaccount_states") or {}).get(state_id)
    if not state_entry:
        return True
    return time.time() - state_entry[1] <= OAUTH_TTL_SECONDS


def google_callback(request):
    _require_provider(settings.GOOGLE_OAUTH_ENABLED)
    if not _valid_state_age(request):
        return HttpResponseBadRequest("OAuth state expired")
    return google_views.oauth2_callback(request)


@require_POST
def kakao_login(request):
    _require_provider(settings.KAKAO_OAUTH_ENABLED)
    return kakao_views.oauth2_login(request)


def kakao_callback(request):
    _require_provider(settings.KAKAO_OAUTH_ENABLED)
    if not _valid_state_age(request):
        return HttpResponseBadRequest("OAuth state expired")
    return kakao_views.oauth2_callback(request)

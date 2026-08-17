from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def production_security_checks(app_configs, **kwargs):
    errors = []
    if settings.DEBUG:
        errors.append(Error("DJANGO_DEBUG must be False", id="accounts.E001"))
    if (
        len(settings.SECRET_KEY) < 50
        or "unsafe" in settings.SECRET_KEY
        or "change-me" in settings.SECRET_KEY
    ):
        errors.append(Error("DJANGO_SECRET_KEY is missing or unsafe", id="accounts.E002"))
    if not settings.ALLOWED_HOSTS or "*" in settings.ALLOWED_HOSTS:
        errors.append(Error("DJANGO_ALLOWED_HOSTS must be explicit", id="accounts.E003"))
    if not settings.SECURE_SSL_REDIRECT or not settings.HTTPS_READY:
        errors.append(Error("Verified HTTPS and SSL redirect are required", id="accounts.E004"))
    if settings.SECURE_HSTS_SECONDS < 31_536_000:
        errors.append(Error("One-year HSTS is required", id="accounts.E005"))
    if settings.TRUST_PROXY_HEADERS and (
        not settings.TRUSTED_PROXY_IPS or settings.TRUSTED_PROXY_HOPS < 1
    ):
        errors.append(Error("Trusted proxy IPs and hop count are required", id="accounts.E006"))
    if settings.GOOGLE_OAUTH_REQUESTED and not settings.GOOGLE_OAUTH_ENABLED:
        errors.append(Error("Google OAuth credentials are incomplete", id="accounts.E007"))
    if settings.KAKAO_OAUTH_REQUESTED and not settings.KAKAO_OAUTH_ENABLED:
        errors.append(Error("Kakao OAuth credentials are incomplete", id="accounts.E008"))
    return errors

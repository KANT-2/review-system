import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as datetime_timezone

from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.conf import settings
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import (
    AuthThrottleBucket,
    EmailResendCooldown,
    User,
    WhitelistEmail,
    canonicalize_email,
)
from audit.services import record_event


class AccountConflictError(Exception):
    pass


class InvalidAccountTransition(Exception):
    pass


@dataclass
class RateLimitExceeded(Exception):
    retry_after: int


def _digest(value):
    return hmac.new(
        settings.SECRET_KEY.encode(), value.encode(), digestmod=hashlib.sha256
    ).hexdigest()


def _advisory_key(value):
    raw = int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")
    return raw - (1 << 64) if raw >= (1 << 63) else raw


def lock_canonical_email(email, *, try_lock=False):
    if connection.vendor != "postgresql":
        return True
    function = "pg_try_advisory_xact_lock" if try_lock else "pg_advisory_xact_lock"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {function}(%s)", [_advisory_key(canonicalize_email(email))])
        result = cursor.fetchone()[0]
    return bool(result) if try_lock else True


def _window_start(now, seconds):
    timestamp = int(now.timestamp())
    return datetime.fromtimestamp(timestamp - (timestamp % seconds), tz=datetime_timezone.utc)


def consume_rate_limit(event_kind, scopes, *, limit, window_seconds):
    now = timezone.now()
    window = _window_start(now, window_seconds)
    expires_at = window + timedelta(seconds=window_seconds)
    with transaction.atomic():
        for scope_kind, value in scopes:
            digest = _digest(str(value))
            try:
                bucket, _ = AuthThrottleBucket.objects.select_for_update().get_or_create(
                    event_kind=event_kind,
                    scope_kind=scope_kind,
                    key_digest=digest,
                    window_started_at=window,
                    defaults={"count": 0, "expires_at": expires_at},
                )
            except IntegrityError:
                bucket = AuthThrottleBucket.objects.select_for_update().get(
                    event_kind=event_kind,
                    scope_kind=scope_kind,
                    key_digest=digest,
                    window_started_at=window,
                )
            if bucket.count >= limit:
                retry_after = max(1, int((bucket.expires_at - now).total_seconds()))
                raise RateLimitExceeded(retry_after)
            bucket.count = F("count") + 1
            bucket.expires_at = expires_at
            bucket.save(update_fields=["count", "expires_at"])


def enforce_resend_cooldown(email, seconds=60):
    now = timezone.now()
    digest = _digest(canonicalize_email(email))
    with transaction.atomic():
        cooldown, _ = EmailResendCooldown.objects.select_for_update().get_or_create(
            key_digest=digest,
            defaults={"allowed_at": now},
        )
        if cooldown.allowed_at > now:
            raise RateLimitExceeded(max(1, int((cooldown.allowed_at - now).total_seconds())))
        cooldown.allowed_at = now + timedelta(seconds=seconds)
        cooldown.save(update_fields=["allowed_at"])


def request_signup(*, request, email):
    """가입 신청은 이메일만 받는다 - 이름·기수·연락처는 승인 뒤 온보딩에서 본인이 채운다."""
    canonical = canonicalize_email(email)
    consume_rate_limit(
        "signup",
        (("ip", request.META.get("REMOTE_ADDR", "unknown")), ("email", canonical)),
        limit=5,
        window_seconds=3600,
    )
    with transaction.atomic():
        lock_canonical_email(canonical)
        if User.objects.filter(email__iexact=canonical).exists():
            return None
        user = User.objects.create_user(
            email=canonical,
            password=None,
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.PENDING,
        )
        address = EmailAddress.objects.select_for_update().get(user=user, primary=True)
        transaction.on_commit(lambda: address.send_confirmation(request, signup=True))
        return user


def resend_confirmation(*, request, email):
    canonical = canonicalize_email(email)
    consume_rate_limit(
        "resend",
        (("ip", request.META.get("REMOTE_ADDR", "unknown")), ("email", canonical)),
        limit=3,
        window_seconds=3600,
    )
    enforce_resend_cooldown(canonical)
    address = EmailAddress.objects.filter(email=canonical, primary=True, verified=False).first()
    if address:
        address.send_confirmation(request, signup=not address.user.has_usable_password())


def store_confirmation_grant(request, key):
    confirmation = EmailConfirmationHMAC.from_key(key)
    if confirmation is None:
        return False
    request.session["email_confirmation_grant"] = {
        "address_id": confirmation.email_address.pk,
        "expires_at": int((timezone.now() + timedelta(minutes=10)).timestamp()),
    }
    request.session.modified = True
    return True


def get_confirmation_address(request):
    grant = request.session.get("email_confirmation_grant") or {}
    if grant.get("expires_at", 0) < int(timezone.now().timestamp()):
        request.session.pop("email_confirmation_grant", None)
        return None
    return EmailAddress.objects.filter(pk=grant.get("address_id"), primary=True).first()


def confirm_email_ownership(request, *, password=None):
    address = get_confirmation_address(request)
    if address is None:
        raise AccountConflictError("확인 요청이 만료되었거나 이미 처리되었습니다.")
    canonical = canonicalize_email(address.email)
    with transaction.atomic():
        lock_canonical_email(canonical)
        user = User.objects.select_for_update().get(pk=address.user_id)
        address = EmailAddress.objects.select_for_update().get(pk=address.pk, primary=True)
        whitelist = WhitelistEmail.objects.select_for_update().filter(email=canonical).first()
        if address.verified:
            raise AccountConflictError("확인 요청이 만료되었거나 이미 처리되었습니다.")
        if not user.has_usable_password():
            if not password:
                raise ValidationError("새 비밀번호를 입력해 주세요.")
            validate_password(password, user=user)
            user.set_password(password)
        address.verified = True
        address.save(update_fields=["verified"])
        if whitelist:
            user.approval_status = User.ApprovalStatus.APPROVED
            user.session_info = whitelist.session_info
        user.email_needs_review = False
        user.save()
    request.session.pop("email_confirmation_grant", None)
    return user


def email_is_verified(user):
    return EmailAddress.objects.filter(
        user=user,
        email=canonicalize_email(user.email),
        primary=True,
        verified=True,
    ).exists()


def finalize_password_login(request, user, *, remember_session):
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if not locked.is_active or locked.approval_status != User.ApprovalStatus.APPROVED:
            raise PermissionDenied
        if not email_is_verified(locked):
            raise PermissionDenied
        version = locked.auth_session_version
        login(request, locked, backend="django.contrib.auth.backends.ModelBackend")
        request.session["auth_session_version"] = version
        request.session.set_expiry(settings.SESSION_COOKIE_AGE if remember_session else 0)
        return locked


def transition_approval(*, actor, target_id, decision):
    if decision not in {User.ApprovalStatus.APPROVED, User.ApprovalStatus.REJECTED}:
        raise InvalidAccountTransition
    with transaction.atomic():
        target = User.objects.select_for_update().get(pk=target_id)
        actor_is_admin = actor.is_application_admin
        actor_is_tutor = (
            actor.role == User.Role.TUTOR
            and actor.is_active
            and actor.approval_status == User.ApprovalStatus.APPROVED
        )
        if not actor_is_admin and not actor_is_tutor:
            raise PermissionDenied
        if target.pk == actor.pk or target.is_superuser:
            raise PermissionDenied
        if actor_is_tutor and target.role != User.Role.STUDENT:
            raise PermissionDenied
        if target.approval_status != User.ApprovalStatus.PENDING:
            raise InvalidAccountTransition
        if not email_is_verified(target):
            raise InvalidAccountTransition
        target.approval_status = decision
        target.auth_session_version = F("auth_session_version") + 1
        target.save(update_fields=["approval_status", "auth_session_version"])
        return target


def _lock_superuser_authority():
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)", [_advisory_key("superuser-authority")]
            )


def set_account_active(*, actor, target_id, is_active, break_glass=False):
    with transaction.atomic():
        _lock_superuser_authority()
        if actor is not None:
            actor = User.objects.select_for_update().get(pk=actor.pk)
        target = User.objects.select_for_update().get(pk=target_id)
        if break_glass:
            if actor is not None:
                raise PermissionDenied
        elif actor is None or not actor.is_application_admin or target.pk == actor.pk:
            raise PermissionDenied
        elif target.is_superuser:
            if not actor.is_superuser:
                raise PermissionDenied
            active_superusers = User.objects.filter(is_superuser=True, is_active=True).count()
            if not is_active and active_superusers <= 1:
                raise InvalidAccountTransition
        target.is_active = is_active
        target.auth_session_version = F("auth_session_version") + 1
        target.save(update_fields=["is_active", "auth_session_version"])
        target.refresh_from_db()
        return target


def change_password(*, request, current_password, new_password):
    user = request.user
    scopes = (
        ("user", user.pk),
        ("session", request.session.session_key or "missing"),
        ("ip", request.META.get("REMOTE_ADDR", "unknown")),
    )
    if not user.check_password(current_password):
        consume_rate_limit("password_change", scopes, limit=5, window_seconds=900)
        raise ValidationError("현재 비밀번호가 올바르지 않습니다.")
    validate_password(new_password, user=user)
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        locked.set_password(new_password)
        locked.must_rotate_password = False
        locked.auth_session_version = F("auth_session_version") + 1
        locked.save()
        locked.refresh_from_db()
        request.user = locked
        update_session_auth_hash(request, locked)
        request.session["auth_session_version"] = locked.auth_session_version
        AuthThrottleBucket.objects.filter(
            event_kind="password_change",
            key_digest__in=[_digest(str(value)) for _, value in scopes],
        ).delete()
        return locked


def cleanup_expired_throttles(limit=500):
    now = timezone.now()
    ids = list(
        AuthThrottleBucket.objects.filter(expires_at__lt=now)
        .order_by("expires_at")
        .values_list("pk", flat=True)[:limit]
    )
    return AuthThrottleBucket.objects.filter(pk__in=ids).delete()[0]


def whitelist_rows():
    """명단 화면용 - 각 이메일이 이미 가입했는지 함께 보여준다."""
    entries = list(WhitelistEmail.objects.all())
    users = {
        canonicalize_email(user.email): user
        for user in User.objects.filter(email__in=[entry.email for entry in entries])
    }
    for entry in entries:
        entry.account = users.get(canonicalize_email(entry.email))
    return entries


@transaction.atomic
def add_whitelist_emails(*, emails, session_info, actor):
    """명단에 이메일을 등록한다. 이미 있으면 기수만 갱신한다."""
    added, updated = [], []
    for email in emails:
        entry, created = WhitelistEmail.objects.update_or_create(
            email=email, defaults={"session_info": session_info}
        )
        (added if created else updated).append(entry)
        record_event(
            action="WHITELIST_ADDED" if created else "WHITELIST_UPDATED",
            target=entry,
            actor=actor,
            summary={"session_info": session_info},
        )
    return added, updated


@transaction.atomic
def remove_whitelist_email(*, entry_id, actor):
    entry = WhitelistEmail.objects.filter(pk=entry_id).first()
    if not entry:
        raise InvalidAccountTransition("이미 삭제된 항목입니다.")
    record_event(
        action="WHITELIST_REMOVED",
        target=entry,
        actor=actor,
        summary={"session_info": entry.session_info},
    )
    entry.delete()
    return entry

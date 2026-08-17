import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as datetime_timezone

from django.conf import settings
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import (
    AuthThrottleBucket,
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


def request_signup(*, request, email, password):
    """가입 신청 - 이메일과 비밀번호를 받아 계정을 만든다.

    확인 메일을 보낼 수 없는 환경이라(발신 도메인 PTR 미설정) 이메일 소유 확인 단계를 두지
    않는다. 대신 명단(WhitelistEmail)에 있는 주소만 자동 승인하고, 나머지는 튜터가 승인 화면
    에서 직접 확인한다.

    이름·기수·연락처는 승인 뒤 온보딩에서 본인이 채운다.
    """
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
            # 가입 여부를 화면에서 알 수 없게 조용히 끝낸다(계정 존재 여부 노출 방지).
            return None
        whitelist = WhitelistEmail.objects.select_for_update().filter(email=canonical).first()
        return User.objects.create_user(
            email=canonical,
            password=password,
            # 소유 확인 단계가 없으므로 allauth 주소 레코드는 처음부터 확인 완료로 둔다.
            _email_verified=True,
            role=User.Role.STUDENT,
            approval_status=(
                User.ApprovalStatus.APPROVED if whitelist else User.ApprovalStatus.PENDING
            ),
            session_info=whitelist.session_info if whitelist else "",
        )


PASSWORD_RESET_GRANT_TTL_SECONDS = 600


def start_password_reset(*, request, email, phone_number):
    """비밀번호 재설정 1단계 - 등록된 이메일과 연락처가 모두 맞아야 통과한다.

    메일을 보낼 수 없어 토큰 링크 대신 지식 기반으로 본인을 확인한다. 토큰 방식보다 약한
    수단이라 시도 횟수를 제한하고, 통과 사실은 서버 세션에만 남긴다 - 2단계에서 대상 계정을
    요청 본문으로 다시 받지 않기 위해서다(받으면 아무 계정이나 바꿀 수 있게 된다).

    성공 여부만 돌려주고 실패 이유는 구분하지 않는다(계정·연락처 존재 여부 노출 방지).
    """
    canonical = canonicalize_email(email)
    consume_rate_limit(
        "password_reset",
        (("ip", request.META.get("REMOTE_ADDR", "unknown")), ("email", canonical)),
        limit=5,
        window_seconds=3600,
    )
    digits = re.sub(r"\D", "", phone_number or "")
    user = User.objects.filter(email=canonical, is_active=True).first()
    if (
        user is None
        or not digits
        or not user.has_usable_password()
        or not user.phone_number
        or re.sub(r"\D", "", user.phone_number) != digits
    ):
        request.session.pop("password_reset_grant", None)
        return False
    request.session["password_reset_grant"] = {
        "user_id": user.pk,
        "expires_at": int(
            (timezone.now() + timedelta(seconds=PASSWORD_RESET_GRANT_TTL_SECONDS)).timestamp()
        ),
    }
    request.session.modified = True
    return True


def finish_password_reset(*, request, new_password):
    """비밀번호 재설정 2단계 - 1단계에서 세션에 남긴 대상 계정에만 적용한다."""
    grant = request.session.get("password_reset_grant") or {}
    if grant.get("expires_at", 0) < int(timezone.now().timestamp()):
        request.session.pop("password_reset_grant", None)
        raise AccountConflictError("본인 확인이 만료되었습니다. 처음부터 다시 진행해 주세요.")
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=grant.get("user_id")).first()
        if user is None or not user.is_active:
            request.session.pop("password_reset_grant", None)
            raise AccountConflictError("본인 확인이 만료되었습니다. 처음부터 다시 진행해 주세요.")
        validate_password(new_password, user=user)
        user.set_password(new_password)
        user.must_rotate_password = False
        # 재설정 전에 열려 있던 세션은 모두 끊는다.
        user.auth_session_version = F("auth_session_version") + 1
        user.save()
        user.refresh_from_db()
    request.session.pop("password_reset_grant", None)
    record_event(action="ACCOUNT_PASSWORD_RESET", target=user, actor_id=None)
    return user


def finalize_password_login(request, user, *, remember_session):
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if not locked.is_active or locked.approval_status != User.ApprovalStatus.APPROVED:
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


def _require_account_authority(actor, target):
    """계정 상태를 바꿀 권한 규칙 - transition_approval과 같은 기준을 쓴다.

    관리자는 전원, 튜터는 수강생만. 자기 계정과 슈퍼유저는 화면에서 건드리지 못한다.
    """
    if target.pk == actor.pk or target.is_superuser:
        raise PermissionDenied
    if actor.is_application_admin:
        return
    is_tutor = (
        actor.role == User.Role.TUTOR
        and actor.is_active
        and actor.approval_status == User.ApprovalStatus.APPROVED
    )
    if not is_tutor or target.role != User.Role.STUDENT:
        raise PermissionDenied


@transaction.atomic
def revert_approval_to_pending(*, actor, target_id):
    """반려한 계정을 승인 대기로 되돌린다 - 반려는 최종 상태가 아니어야 한다."""
    target = User.objects.select_for_update().get(pk=target_id)
    _require_account_authority(actor, target)
    if target.approval_status != User.ApprovalStatus.REJECTED:
        raise InvalidAccountTransition("반려된 계정만 승인 대기로 되돌릴 수 있습니다.")
    target.approval_status = User.ApprovalStatus.PENDING
    target.auth_session_version = F("auth_session_version") + 1
    target.save(update_fields=["approval_status", "auth_session_version"])
    record_event(
        action="ACCOUNT_APPROVAL_REVERTED",
        target=target,
        actor=actor,
        summary={"to": User.ApprovalStatus.PENDING},
    )
    target.refresh_from_db()
    return target


@transaction.atomic
def change_user_role(*, actor, target_id, role):
    """수강생과 튜터 사이의 역할만 바꾼다.

    관리자 역할은 is_staff와 함께 움직여야 해서(accounts_staff_role_consistent 제약) 화면에서
    다루지 않는다 - 권한 상승 경로를 만들지 않기 위해서다.
    """
    if role not in {User.Role.STUDENT, User.Role.TUTOR}:
        raise InvalidAccountTransition("수강생과 튜터 사이에서만 역할을 바꿀 수 있습니다.")
    target = User.objects.select_for_update().get(pk=target_id)
    if not actor.is_application_admin:
        raise PermissionDenied
    if target.pk == actor.pk or target.is_superuser or target.role == User.Role.ADMIN:
        raise PermissionDenied
    if target.role == role:
        raise InvalidAccountTransition("이미 같은 역할입니다.")
    previous = target.role
    target.role = role
    target.auth_session_version = F("auth_session_version") + 1
    target.save(update_fields=["role", "auth_session_version"])
    record_event(
        action="ACCOUNT_ROLE_CHANGED",
        target=target,
        actor=actor,
        summary={"from": previous, "to": role},
    )
    target.refresh_from_db()
    return target


@transaction.atomic
def require_password_rotation(*, actor, target_id):
    """다음 로그인에서 비밀번호를 새로 정하게 만든다(기존 세션도 함께 끊는다)."""
    target = User.objects.select_for_update().get(pk=target_id)
    _require_account_authority(actor, target)
    target.must_rotate_password = True
    target.auth_session_version = F("auth_session_version") + 1
    target.save(update_fields=["must_rotate_password", "auth_session_version"])
    record_event(action="ACCOUNT_PASSWORD_ROTATION_REQUIRED", target=target, actor=actor)
    target.refresh_from_db()
    return target


def account_rows(*, role=None, status=None, query=None):
    """계정 관리 화면 목록."""
    users = User.objects.exclude(is_superuser=True).order_by("role", "email")
    if role:
        users = users.filter(role=role)
    if status:
        users = users.filter(approval_status=status)
    if query:
        users = users.filter(email__icontains=query) | users.filter(first_name__icontains=query)
    return users


@transaction.atomic
def update_account_profile(*, actor, target_id, first_name, student_number, session_info):
    """계정 관리 화면에서 이름·식별번호·기수를 고친다(ACC-001).

    식별번호는 회차 시작 때 참가자 스냅샷으로 동결되므로, 여기서 바꿔도 이미 시작된
    회차의 명단은 그대로다(ACC-003).
    """
    target = User.objects.select_for_update().get(pk=target_id)
    _require_account_authority(actor, target)
    number = (student_number or "").strip() or None
    if number and User.objects.filter(student_number=number).exclude(pk=target.pk).exists():
        raise InvalidAccountTransition("이미 다른 계정이 쓰는 식별번호입니다.")
    changed = {}
    for field, value in (
        ("first_name", (first_name or "").strip()),
        ("student_number", number),
        ("session_info", (session_info or "").strip()),
    ):
        if getattr(target, field) != value:
            changed[field] = value
            setattr(target, field, value)
    if not changed:
        return target
    target.save(update_fields=tuple(changed))
    record_event(
        action="ACCOUNT_PROFILE_UPDATED",
        target=target,
        actor=actor,
        # 값 자체가 아니라 어떤 항목을 건드렸는지만 남긴다.
        summary={"fields": sorted(changed)},
    )
    return target

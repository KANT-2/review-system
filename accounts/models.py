from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


def canonicalize_email(email):
    return BaseUserManager.normalize_email((email or "").strip()).lower()


class UserQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if "email" in kwargs:
            raise ValueError("이메일은 canonical email service를 통해서만 변경할 수 있습니다.")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        raise ValueError("사용자는 UserManager를 통해 개별 생성해야 합니다.")

    def bulk_update(self, objs, fields, **kwargs):
        if "email" in fields:
            raise ValueError("이메일은 canonical email service를 통해서만 변경할 수 있습니다.")
        return super().bulk_update(objs, fields, **kwargs)


class UserManager(BaseUserManager.from_queryset(UserQuerySet)):
    def create_user(self, email, password=None, **extra_fields):
        email_verified = extra_fields.pop("_email_verified", False)
        if not email:
            raise ValueError("이메일은 필수 입력 항목입니다.")
        with transaction.atomic():
            user = self.model(email=canonicalize_email(email), **extra_fields)
            if password:
                user.set_password(password)
            else:
                user.set_unusable_password()
            user.save(using=self._db)
            if email_verified:
                from allauth.account.models import EmailAddress

                EmailAddress.objects.filter(user=user, primary=True).update(verified=True)
            return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault("approval_status", User.ApprovalStatus.APPROVED)
        extra_fields.setdefault("is_onboarded", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("슈퍼유저는 is_staff=True이어야 합니다.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("슈퍼유저는 is_superuser=True이어야 합니다.")
        if extra_fields.get("role") != User.Role.ADMIN:
            raise ValueError("슈퍼유저는 ADMIN 역할이어야 합니다.")
        if extra_fields.get("approval_status") != User.ApprovalStatus.APPROVED:
            raise ValueError("슈퍼유저는 승인 상태여야 합니다.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", _("수강생")
        TUTOR = "tutor", _("튜터")
        ADMIN = "admin", _("관리자")

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", _("대기")
        APPROVED = "approved", _("승인")
        REJECTED = "rejected", _("반려")

    username = None
    email = models.EmailField(_("이메일"), unique=True)
    role = models.CharField(_("역할"), max_length=20, choices=Role.choices, default=Role.STUDENT)
    approval_status = models.CharField(
        _("승인 상태"),
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    is_onboarded = models.BooleanField(_("온보딩 완료 여부"), default=False)
    is_social_account = models.BooleanField(_("소셜 계정 여부"), default=False)
    student_number = models.CharField(
        _("수강생 식별번호"), max_length=32, null=True, blank=True, unique=True
    )
    phone_number = models.CharField(_("연락처"), max_length=20, blank=True, default="")
    # 마이페이지에서 본인이 올린다. 비어 있으면 이름 첫 글자 아바타를 그대로 쓴다.
    profile_image = models.ImageField(
        _("프로필 사진"), upload_to="profiles/", blank=True, null=True
    )
    auth_session_version = models.PositiveBigIntegerField(_("인증 세션 버전"), default=0)
    must_rotate_password = models.BooleanField(_("비밀번호 변경 필요"), default=False)
    email_needs_review = models.BooleanField(_("이메일 재확인 필요"), default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("사용자")
        verbose_name_plural = _("사용자 목록")
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
            # 튜터도 운영 담당자라 관리자 화면을 쓴다. 수강생은 여전히 들어갈 수 없다.
            models.CheckConstraint(
                condition=models.Q(is_staff=True, role__in=("admin", "tutor"))
                | models.Q(is_staff=False, role="student"),
                name="accounts_staff_role_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(is_superuser=False)
                | models.Q(is_staff=True, approval_status="approved"),
                name="accounts_superuser_authority_consistent",
            ),
        ]

    #: 관리자 화면을 쓰는 역할. 제약(accounts_staff_role_consistent)과 같은 목록이어야 한다.
    STAFF_ROLES = ("admin", "tutor")

    def save(self, *args, **kwargs):
        self.email = canonicalize_email(self.email)
        # 역할이 접근 권한을 정한다 - 역할만 바꾸면 관리자 화면 접근이 따라온다.
        # queryset.update()처럼 save()를 건너뛰는 경로는 위 DB 제약이 막는다.
        expected_staff = self.role in self.STAFF_ROLES
        if self.is_staff != expected_staff:
            self.is_staff = expected_staff
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "is_staff"}
        if self.pk:
            previous_email = (
                type(self).objects.filter(pk=self.pk).values_list("email", flat=True).first()
            )
            if previous_email and canonicalize_email(previous_email) != self.email:
                raise ValueError("이메일 변경은 현재 지원하지 않습니다.")
        super().save(*args, **kwargs)

    def __str__(self):
        name = self.first_name if self.first_name else self.email
        return f"{name} ({self.get_role_display()})"

    @property
    def login_provider(self):
        social_account = self.socialaccount_set.order_by("provider").first()
        return social_account.provider if social_account else "email"

    @property
    def is_application_admin(self):
        return (
            self.role == self.Role.ADMIN
            and self.is_staff
            and self.is_active
            and self.approval_status == self.ApprovalStatus.APPROVED
        )


class WhitelistEmail(models.Model):
    email = models.EmailField(_("사전 등록 이메일"), unique=True)
    created_at = models.DateTimeField(_("등록 일시"), auto_now_add=True)

    class Meta:
        verbose_name = _("학생 화이트리스트 이메일")
        verbose_name_plural = _("학생 화이트리스트 이메일 목록")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_whitelist_email_ci_unique")
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = canonicalize_email(self.email)
        super().save(*args, **kwargs)


class AuthThrottleBucket(models.Model):
    event_kind = models.CharField(max_length=32)
    scope_kind = models.CharField(max_length=16)
    key_digest = models.CharField(max_length=64)
    window_started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event_kind", "scope_kind", "key_digest", "window_started_at"),
                name="accounts_throttle_bucket_unique",
            )
        ]

    def __str__(self):
        return f"{self.event_kind}:{self.scope_kind}:{self.window_started_at.isoformat()}"


class EmailVerificationCode(models.Model):
    class Purpose(models.TextChoices):
        SIGNUP = "SIGNUP", _("회원가입")
        PASSWORD_RESET = "PASSWORD_RESET", _("비밀번호 재설정")

    email = models.EmailField(_("이메일"))
    code = models.CharField(_("인증코드 6자리"), max_length=6)
    purpose = models.CharField(_("인증 목적"), max_length=20, choices=Purpose.choices)
    is_verified = models.BooleanField(_("인증 완료 여부"), default=False)
    created_at = models.DateTimeField(_("생성 일시"), auto_now_add=True)
    expires_at = models.DateTimeField(_("만료 일시"), db_index=True)

    class Meta:
        verbose_name = _("이메일 인증코드")
        verbose_name_plural = _("이메일 인증코드 목록")
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_purpose_display()}] {self.email} - {self.code}"


class ScheduledEmail(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("대기 중")
        SENT = "SENT", _("발송 완료")
        CANCELLED = "CANCELLED", _("취소됨")
        FAILED = "FAILED", _("발송 실패")

    class TargetType(models.TextChoices):
        ALL = "ALL", _("전체 수강생")
        TEAM = "TEAM", _("조(팀) 선택")
        SELECT = "SELECT", _("개인 수강생 선택")
        SINGLE = "SINGLE", _("개별 수강생 1인")

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="scheduled_emails",
        verbose_name=_("발송자"),
    )
    subject = models.CharField(_("메일 제목"), max_length=200)
    message = models.TextField(_("메일 내용"))
    target_type = models.CharField(
        _("발송 대상 유형"), max_length=20, choices=TargetType.choices, default=TargetType.ALL
    )
    target_team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("대상 조(팀)"),
    )
    selected_user_ids_json = models.TextField(
        _("선택 유저 ID 목록 (JSON)"), blank=True, default="[]"
    )
    scheduled_at = models.DateTimeField(_("예약 발송 일시"), db_index=True)
    status = models.CharField(
        _("발송 상태"), max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    sent_at = models.DateTimeField(_("실제 발송 일시"), null=True, blank=True)
    sent_count = models.IntegerField(_("발송 건수"), default=0)
    created_at = models.DateTimeField(_("생성 일시"), auto_now_add=True)

    class Meta:
        verbose_name = _("예약 이메일 공지")
        verbose_name_plural = _("예약 이메일 공지 목록")
        ordering = ["-scheduled_at", "-created_at"]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.subject} ({self.scheduled_at.strftime('%Y-%m-%d %H:%M')})"

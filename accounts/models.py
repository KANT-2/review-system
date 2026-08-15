from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """이메일을 식별자로 사용하는 커스텀 유저 매니저"""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('이메일은 필수 입력 항목입니다.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', User.Role.ADMIN)
        extra_fields.setdefault('approval_status', User.ApprovalStatus.APPROVED)
        extra_fields.setdefault('is_onboarded', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('슈퍼유저는 is_staff=True이어야 합니다.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('슈퍼유저는 is_superuser=True이어야 합니다.')

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """AX 평가 시스템 커스텀 사용자 모델"""

    class Role(models.TextChoices):
        STUDENT = 'student', _('수강생')
        TUTOR = 'tutor', _('튜터')
        ADMIN = 'admin', _('관리자')

    class ApprovalStatus(models.TextChoices):
        PENDING = 'pending', _('대기')
        APPROVED = 'approved', _('승인')
        REJECTED = 'rejected', _('반려')

    # username 필드 비활성화 및 email을 기본 식별자로 설정
    username = None
    email = models.EmailField(_('이메일'), unique=True)

    # 권한 및 승인 상태
    role = models.CharField(
        _('역할'),
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
    )
    approval_status = models.CharField(
        _('승인 상태'),
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )

    # 온보딩 및 계정 유형 플래그
    is_onboarded = models.BooleanField(_('온보딩 완료 여부'), default=False)
    is_social_account = models.BooleanField(_('소셜 계정 여부'), default=False)

    # 추가 정보
    session_info = models.CharField(_('기수 정보'), max_length=50, blank=True, null=True)
    phone_number = models.CharField(_('연락처'), max_length=20, blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _('사용자')
        verbose_name_plural = _('사용자 목록')

    def __str__(self):
        name = self.first_name if self.first_name else self.email
        return f"{name} ({self.get_role_display()})"

    @property
    def login_provider(self):
        """가입/로그인 수단 반환 (kakao / google / email)"""
        if not self.is_social_account:
            return 'email'
        social_acc = self.socialaccount_set.first()
        return social_acc.provider if social_acc else 'email'


class WhitelistEmail(models.Model):
    """사전 승인 대상 이메일 화이트리스트 모델"""

    email = models.EmailField(_('사전 등록 이메일'), unique=True)
    role = models.CharField(
        _('부여 역할'),
        max_length=20,
        choices=User.Role.choices,
        default=User.Role.STUDENT,
    )
    session_info = models.CharField(_('배정 기수'), max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(_('등록 일시'), auto_now_add=True)

    class Meta:
        verbose_name = _('화이트리스트 이메일')
        verbose_name_plural = _('화이트리스트 이메일 목록')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"
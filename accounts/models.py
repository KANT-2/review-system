from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    """
    PRD 스펙 반영 커스텀 사용자 모델
    """
    class Role(models.TextChoices):
        STUDENT = 'STUDENT', '학생'
        TUTOR = 'TUTOR', '튜터'
        ADMIN = 'ADMIN', '관리자'

    class ApprovalStatus(models.TextChoices):
        PENDING = 'PENDING', '승인 대기'
        APPROVED = 'APPROVED', '승인 완료'
        REJECTED = 'REJECTED', '승인 거절'

    email = models.EmailField('이메일', unique=True)
    role = models.CharField('역할', max_length=10, choices=Role.choices, default=Role.STUDENT)
    approval_status = models.CharField('승인 상태', max_length=10, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    
    # 온보딩 및 프로필 정보
    is_onboarded = models.BooleanField('온보딩 완료 여부', default=False)
    session_info = models.CharField('기수/세션', max_length=50, blank=True, null=True)  # 예: 4기 풀스택 트랙
    phone = models.CharField('전화번호', max_length=20, blank=True, null=True)
    profile_image = models.ImageField('프로필 사진', upload_to='profiles/', blank=True, null=True)
    is_social_account = models.BooleanField('소셜 로그인 계정 여부', default=False)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        verbose_name = '사용자'
        verbose_name_plural = '사용자 목록'

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.email})"


class WhitelistEmail(models.Model):
    """
    사전 등록 화이트리스트 DB (일치 시 가입 즉시 자동 승인)
    """
    email = models.EmailField('사전 등록 이메일', unique=True)
    name = models.CharField('이름', max_length=30)
    session_info = models.CharField('기수/세션', max_length=50, default='4기')
    role = models.CharField('역할', max_length=10, choices=User.Role.choices, default=User.Role.STUDENT)
    created_at = models.DateTimeField('등록일', auto_now_add=True)

    class Meta:
        verbose_name = '화이트리스트'
        verbose_name_plural = '화이트리스트 목록'

    def __str__(self):
        return f"{self.name} - {self.email} ({self.session_info})"
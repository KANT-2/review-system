from allauth.account.models import EmailAddress
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "운영 전 privileged 계정의 이메일 확인과 비밀번호 교체 상태를 검사합니다."

    def handle(self, *args, **options):
        privileged = User.objects.filter(
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
            role__in=(User.Role.TUTOR, User.Role.ADMIN),
        )
        failures = []
        for user in privileged:
            verified = EmailAddress.objects.filter(
                user=user, email=user.email, primary=True, verified=True
            ).exists()
            if not verified or (user.has_usable_password() and user.must_rotate_password):
                failures.append(user.pk)
        if failures:
            raise CommandError(f"인증 준비가 끝나지 않은 privileged user IDs: {failures}")
        self.stdout.write(self.style.SUCCESS("Authentication readiness checks passed."))

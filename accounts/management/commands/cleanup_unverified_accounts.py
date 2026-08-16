from datetime import timedelta

from allauth.account.models import EmailAddress
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from accounts.services import cleanup_expired_throttles, lock_canonical_email


class Command(BaseCommand):
    help = "7일 지난 안전한 미인증 가입 계정과 만료된 rate-limit bucket을 정리합니다."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=7)
        candidate_ids = list(
            User.objects.filter(
                date_joined__lt=cutoff,
                approval_status=User.ApprovalStatus.PENDING,
                role=User.Role.STUDENT,
                is_staff=False,
                is_superuser=False,
                last_login__isnull=True,
                socialaccount__isnull=True,
                emailaddress__verified=False,
            )
            .values_list("pk", flat=True)
            .distinct()[:100]
        )
        deleted = 0
        for user_id in candidate_ids:
            with transaction.atomic():
                candidate = User.objects.filter(pk=user_id).values("email").first()
                if candidate is None or not lock_canonical_email(candidate["email"], try_lock=True):
                    continue
                user = User.objects.select_for_update().filter(pk=user_id).first()
                if user is None or not self._is_safe(user, cutoff):
                    continue
                EmailAddress.objects.select_for_update().filter(user=user)
                user.delete()
                deleted += 1
        throttles = cleanup_expired_throttles()
        self.stdout.write(self.style.SUCCESS(f"accounts={deleted}, throttle_rows={throttles}"))

    @staticmethod
    def _is_safe(user, cutoff):
        return (
            user.date_joined < cutoff
            and user.approval_status == User.ApprovalStatus.PENDING
            and user.role == User.Role.STUDENT
            and not user.is_staff
            and not user.is_superuser
            and user.last_login is None
            and not user.socialaccount_set.exists()
            and not user.emailaddress_set.filter(verified=True).exists()
        )

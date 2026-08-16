from django.core.management.base import BaseCommand, CommandError

from accounts.models import User, canonicalize_email
from accounts.services import set_account_active


class Command(BaseCommand):
    help = "침해 사고 대응용 local-console break-glass 계정 정지 명령입니다."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("--confirm 옵션이 필요합니다.")
        email = canonicalize_email(options["email"])
        try:
            target = User.objects.get(email=email)
        except User.DoesNotExist as error:
            raise CommandError("사용자를 찾을 수 없습니다.") from error
        set_account_active(actor=None, target_id=target.pk, is_active=False, break_glass=True)
        self.stdout.write(self.style.WARNING(f"Suspended user ID {target.pk}."))

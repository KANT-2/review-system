from django.core.management.base import BaseCommand

from accounts.services import cleanup_expired_throttles


class Command(BaseCommand):
    """만료된 rate-limit bucket을 정리한다.

    이메일 소유 확인 단계를 없애면서(가입 시 비밀번호를 바로 설정한다) 예전
    cleanup_unverified_accounts 가 하던 "미인증 가입 계정 삭제"는 없앴다. 이제 모든 가입
    계정의 주소가 확인 완료로 저장되므로, 그 조건에 걸리는 계정은 관리자가 직접 만든
    계정뿐이라 자동 삭제 대상이 될 수 없다.
    """

    help = "만료된 rate-limit bucket을 정리합니다."

    def handle(self, *args, **options):
        throttles = cleanup_expired_throttles()
        self.stdout.write(self.style.SUCCESS(f"throttle_rows={throttles}"))

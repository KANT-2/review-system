import os

import django

# Django 환경 설정
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from accounts.models import User, WhitelistEmail  # noqa: E402


def seed():
    print("🌱 [1/3] 화이트리스트 사전 등록 데이터 생성 중...")
    whitelists = [
        {
            "email": "student1@ax.com",
            "name": "김민준",
            "session_info": "4기 풀스택 트랙",
            "role": User.Role.STUDENT,
        },
        {
            "email": "student2@ax.com",
            "name": "이수진",
            "session_info": "4기 프론트엔드 트랙",
            "role": User.Role.STUDENT,
        },
        {
            "email": "student3@ax.com",
            "name": "박도현",
            "session_info": "4기 백엔드 트랙",
            "role": User.Role.STUDENT,
        },
        {
            "email": "tutor.park@ax.com",
            "name": "박교수",
            "session_info": "전담 튜터진",
            "role": User.Role.TUTOR,
        },
    ]
    for w in whitelists:
        WhitelistEmail.objects.update_or_create(email=w["email"], defaults=w)

    print("👥 [2/3] 테스트 계정(튜터, 정회원 학생, 승인대기자) 생성 중...")

    # 1. 튜터 계정 (ID: tutor@ax.com / PW: password123)
    tutor, _ = User.objects.update_or_create(
        email="tutor@ax.com",
        defaults={
            "username": "tutor@ax.com",
            "first_name": "박교수",
            "role": User.Role.TUTOR,
            "approval_status": User.ApprovalStatus.APPROVED,
            "is_onboarded": True,
            "is_staff": True,
            "session_info": "메인 튜터",
            "phone": "010-9999-8888",
        },
    )
    tutor.set_password("password123")
    tutor.save()

    # 2. 메인 학생 계정 (ID: student@ax.com / PW: password123)
    main_student, _ = User.objects.update_or_create(
        email="student@ax.com",
        defaults={
            "username": "student@ax.com",
            "first_name": "김민준",
            "role": User.Role.STUDENT,
            "approval_status": User.ApprovalStatus.APPROVED,
            "is_onboarded": True,
            "session_info": "4기 풀스택 트랙",
            "phone": "010-1234-5678",
        },
    )
    main_student.set_password("password123")
    main_student.save()

    # 3. 같은 기수 승인 완료 학생들 (8명)
    students_data = [
        ("이수진", "sujin.lee@ax.com", "010-2222-3333"),
        ("박도현", "dohyun.park@ax.com", "010-3333-4444"),
        ("최민아", "mina.choi@ax.com", "010-4444-5555"),
        ("강태호", "taeho.kang@ax.com", "010-5555-6666"),
        ("윤아름", "areum.yoon@ax.com", "010-6666-7777"),
        ("정유진", "yujin.jung@ax.com", "010-7777-8888"),
        ("오세훈", "sehun.oh@ax.com", "010-8888-9999"),
        ("배수지", "suji.bae@ax.com", "010-1111-2222"),
    ]
    for name, email, phone in students_data:
        st, _ = User.objects.update_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": name,
                "role": User.Role.STUDENT,
                "approval_status": User.ApprovalStatus.APPROVED,
                "is_onboarded": True,
                "session_info": "4기 풀스택 트랙",
                "phone": phone,
            },
        )
        st.set_password("password123")
        st.save()

    # 4. 가입 승인 대기 큐 대상자들 (4명 - 튜터 관리 화면 심사용)
    pending_data = [
        ("정우성", "woosung.jung@gmail.com", "010-9001-1001"),
        ("한지민", "jimin.han@naver.com", "010-9002-1002"),
        ("송중기", "joongki.song@kakao.com", "010-9003-1003"),
        ("김태리", "taeri.kim@gmail.com", "010-9004-1004"),
    ]
    for name, email, phone in pending_data:
        pu, _ = User.objects.update_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": name,
                "role": User.Role.STUDENT,
                "approval_status": User.ApprovalStatus.PENDING,
                "is_onboarded": False,
                "session_info": "4기 신청자",
                "phone": phone,
            },
        )
        pu.set_password("password123")
        pu.save()

    print("🎉 [3/3] 더미 데이터 생성 완료!")
    print("━" * 50)
    print("🔑 [로그인 테스트 계정 정보]")
    print(" • 메인 학생 계정: student@ax.com  (비밀번호: password123)")
    print(" • 전담 튜터 계정: tutor@ax.com    (비밀번호: password123)")
    print(" • 승인 대기 계정: woosung.jung@gmail.com (비밀번호: password123)")
    print("━" * 50)


if __name__ == "__main__":
    seed()

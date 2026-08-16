import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from allauth.account.models import EmailAddress  # noqa: E402

from accounts.models import User, WhitelistEmail  # noqa: E402

DEV_PASSWORD = "Local-Only-Strong-Password-2026!"


def ensure_user(*, email, name, role, approval_status, session_info, phone_number=""):
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(
            email=email,
            password=DEV_PASSWORD,
            _email_verified=True,
            first_name=name,
            role=role,
            approval_status=approval_status,
            session_info=session_info,
            phone_number=phone_number,
            is_onboarded=approval_status == User.ApprovalStatus.APPROVED,
        )
    else:
        user.first_name = name
        user.role = role
        user.approval_status = approval_status
        user.session_info = session_info
        user.phone_number = phone_number
        user.is_staff = role == User.Role.ADMIN
        user.set_password(DEV_PASSWORD)
        user.save()
        EmailAddress.objects.filter(user=user, primary=True).update(verified=True)
    return user


def seed():
    print("Creating student whitelist entries...")
    for email, session_info in (
        ("student1@ax.com", "4기 풀스택 트랙"),
        ("student2@ax.com", "4기 프론트엔드 트랙"),
        ("student3@ax.com", "4기 백엔드 트랙"),
    ):
        WhitelistEmail.objects.update_or_create(
            email=email,
            defaults={"session_info": session_info},
        )

    ensure_user(
        email="tutor@ax.com",
        name="박교수",
        role=User.Role.TUTOR,
        approval_status=User.ApprovalStatus.APPROVED,
        session_info="메인 튜터",
    )
    ensure_user(
        email="student@ax.com",
        name="김민준",
        role=User.Role.STUDENT,
        approval_status=User.ApprovalStatus.APPROVED,
        session_info="4기 풀스택 트랙",
        phone_number="010-1234-5678",
    )
    for name, email in (
        ("이수진", "sujin.lee@ax.com"),
        ("박도현", "dohyun.park@ax.com"),
        ("최민아", "mina.choi@ax.com"),
        ("강태호", "taeho.kang@ax.com"),
    ):
        ensure_user(
            email=email,
            name=name,
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            session_info="4기 풀스택 트랙",
        )
    for name, email in (
        ("정우성", "woosung.jung@example.com"),
        ("한지민", "jimin.han@example.com"),
    ):
        ensure_user(
            email=email,
            name=name,
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.PENDING,
            session_info="4기 신청자",
        )

    print("Development seed data created.")
    print("Password for seeded users:", DEV_PASSWORD)


if __name__ == "__main__":
    seed()

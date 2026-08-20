from django.db import migrations, models


def grant_admin_access_to_tutors(apps, schema_editor):
    """튜터도 Django 관리자 화면을 쓰는 운영 담당자다 - 기존 튜터에게 접근 권한을 준다."""
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="tutor").update(is_staff=True)


def revoke_admin_access_from_tutors(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="tutor").update(is_staff=False)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_drop_session_info"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="user",
            name="accounts_staff_role_consistent",
        ),
        # 제약을 다시 걸기 전에 기존 데이터를 새 규칙에 맞춘다.
        migrations.RunPython(grant_admin_access_to_tutors, revoke_admin_access_from_tutors),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("is_staff", True), ("role__in", ("admin", "tutor"))),
                    models.Q(("is_staff", False), ("role", "student")),
                    _connector="OR",
                ),
                name="accounts_staff_role_consistent",
            ),
        ),
    ]

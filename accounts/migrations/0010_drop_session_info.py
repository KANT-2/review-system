from django.db import migrations


class Migration(migrations.Migration):
    """기수는 화면에서 쓰지 않기로 해 입력·표시와 함께 저장도 걷어낸다."""

    dependencies = [
        ("accounts", "0009_merge_profile_image_and_email"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="session_info",
        ),
        migrations.RemoveField(
            model_name="whitelistemail",
            name="session_info",
        ),
    ]

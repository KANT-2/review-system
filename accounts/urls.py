from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("logout/", views.logout_view, name="logout"),
    path("password/change/", views.password_change_view, name="password_change"),
    path("onboarding/", views.onboarding_view, name="onboarding"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("mypage/", views.mypage_view, name="mypage"),
    path(
        "mypage/rounds/<int:round_id>/result.csv",
        views.mypage_round_result_csv,
        name="mypage_round_result_csv",
    ),
    path("tutor/accounts/", views.account_admin, name="account_admin"),
    # note 경로는 account_action의 <str:action>에 먹히지 않도록 먼저 선언한다.
    path("tutor/accounts/<int:user_id>/note/", views.save_student_note, name="save_student_note"),
    path(
        "tutor/accounts/<int:user_id>/note/<int:note_id>/delete/",
        views.delete_student_note,
        name="delete_student_note",
    ),
    path(
        "tutor/accounts/<int:user_id>/note/delete-all/",
        views.delete_all_student_notes,
        name="delete_all_student_notes",
    ),
    path(
        "tutor/accounts/<int:user_id>/<str:action>/",
        views.account_action,
        name="account_action",
    ),
    path("tutor/whitelist/", views.whitelist_add, name="whitelist_add"),
    path("tutor/whitelist/<int:entry_id>/delete/", views.whitelist_delete, name="whitelist_delete"),
    path("tutor/approve/<int:user_id>/", views.approve_user, name="approve_user"),
    path("tutor/reject/<int:user_id>/", views.reject_user, name="reject_user"),
    path("tutor/approvals/bulk/", views.bulk_approval, name="bulk_approval"),
    path("api/onboarding/", views.api_onboarding, name="api_onboarding"),
    path("api/signup/", views.signup_api, name="api_signup"),
    path(
        "api/password/verify/",
        views.password_reset_verify_api,
        name="api_password_reset_verify",
    ),
    path("api/password/reset/", views.password_reset_api, name="api_password_reset"),
    path("api/users/<int:user_id>/approve/", views.approve_user_api, name="api_approve_user"),
    path("api/users/<int:user_id>/reject/", views.reject_user_api, name="api_reject_user"),
    path("api/profile/update/", views.update_profile_api, name="api_update_profile"),
]

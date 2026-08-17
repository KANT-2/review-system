from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    # 인증 및 기본 화면
    path("login/", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("logout/", views.logout_view, name="logout"),
    # 대시보드 및 마이페이지
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("mypage/", views.mypage_view, name="mypage"),
    # 튜터 승인 관리 콘솔
    path("tutor/admin/", views.tutor_dashboard, name="tutor_admin"),
    path("tutor/approve/<int:user_id>/", views.approve_user, name="approve_user"),
    path("tutor/reject/<int:user_id>/", views.reject_user, name="reject_user"),
    # 비동기(AJAX) API 엔드포인트
    path("api/onboarding/", views.api_onboarding, name="api_onboarding"),
    path("api/signup/", views.signup_api, name="api_signup"),
    path("api/password/verify/", views.verify_user_for_reset_api, name="api_verify_user_for_reset"),
    path("api/password/reset/", views.reset_password_api, name="api_reset_password"),
    path("api/users/<int:user_id>/approve/", views.approve_user_api, name="api_approve_user"),
    path("api/users/<int:user_id>/reject/", views.reject_user_api, name="api_reject_user"),
    path("api/profile/update/", views.update_profile_api, name="api_update_profile"),
]

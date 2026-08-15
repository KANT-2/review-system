from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('onboarding/', views.onboarding_view, name='onboarding'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('mypage/', views.mypage_view, name='mypage'),
    path('tutor/', views.tutor_admin_view, name='tutor_admin'),
    
    # 비동기 API 엔드포인트
    path('api/signup/', views.signup_api, name='api_signup'),
    path('api/password/verify/', views.verify_user_for_reset_api, name='api_verify_user_for_reset'),
    path('api/password/reset/', views.reset_password_api, name='api_reset_password'),
    path('api/users/<int:user_id>/approve/', views.approve_user_api, name='api_approve_user'),
    path('api/users/<int:user_id>/reject/', views.reject_user_api, name='api_reject_user'),
    path('api/profile/update/', views.update_profile_api, name='api_update_profile'),
]
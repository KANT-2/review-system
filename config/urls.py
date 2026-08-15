from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # 커스텀 뷰(디자인 템플릿)를 allauth 기본 뷰보다 우선 적용
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("allauth.urls")),
    path("", lambda request: redirect("accounts:login")),
]

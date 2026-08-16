from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from accounts import oauth
from accounts import views as account_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("accounts/google/login/", oauth.google_login, name="google_login"),
    path(
        "accounts/google/login/callback/",
        oauth.google_callback,
        name="google_callback",
    ),
    path("accounts/kakao/login/", oauth.kakao_login, name="kakao_login"),
    path(
        "accounts/kakao/login/callback/",
        oauth.kakao_callback,
        name="kakao_callback",
    ),
    path("teams/", include("teams.urls")),
    path("", account_views.home_view, name="home"),
]

if settings.ENABLE_DEV_PREVIEWS:
    urlpatterns.append(path("results/", include("results.urls")))

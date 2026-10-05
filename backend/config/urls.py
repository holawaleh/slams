from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import (TokenObtainPairView,
                                            TokenRefreshView, TokenVerifyView)
from django.http import JsonResponse
from core.auth_views import RegisterView, AcceptInviteView, LoginView


def api_root(request):
    return JsonResponse({
        "service": "SLAM",
        "status": "ok",
        "endpoints": {
            "admin": "/admin/",
            "register": "/api/auth/register/",
            "login": "/api/auth/login/",
            "me": "/api/me/",
            "browsable_api": "/api/",
            "device_api": "/api/device/",
        },
    })

urlpatterns = [
    path("", api_root),
    path("admin/", admin.site.urls),
    path("api/auth/register/", RegisterView.as_view(),      name="register"),
    path("api/auth/invite/",   AcceptInviteView.as_view(),   name="accept-invite"),
    path("api/auth/login/",   LoginView.as_view(), name="login"),
    path("api/auth/refresh/", TokenRefreshView.as_view(),    name="refresh"),
    path("api/auth/verify/",  TokenVerifyView.as_view(),     name="verify"),
    path("api/", include("core.urls")),
    path("api/device/", include("deviceapi.urls")),
]



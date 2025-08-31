from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from expenses.views import RegisterView, LogoutView  

urlpatterns = [
    path('admin/', admin.site.urls),

    # --- Auth (JWT) ---
    path('api/auth/register/', RegisterView.as_view(), name='auth-register'),
    path('api/auth/login/', TokenObtainPairView.as_view(), name='auth-login'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='auth-refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='auth-logout'),

    # --- App endpoints ---
    path('api/', include('expenses.urls')),
    
    # Schema & Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # --- DRF browsable API login/logout ---
    path('api/auth/browse/', include('rest_framework.urls')),  # optional, for browsable API
]

# dashboard/urls.py
from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    # Main dashboard with timeline
    path('', views.DashboardView.as_view(), name='dashboard'),
]
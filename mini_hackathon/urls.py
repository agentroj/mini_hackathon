from django.contrib import admin
from django.urls import path, include
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.about, name='about'),
    path('projects/', views.projects, name='projects'),
    path('report/', views.report, name='report'),
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]

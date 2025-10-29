from django.urls import path
from . import views
from . import views_quickbooks as qb

urlpatterns = [
    path('', views.about, name='home'),
    path('about/', views.about, name='about'),
    path('projects/', views.projects, name='projects'),
    path('report/', views.report, name='report'),

    # QuickBooks OAuth endpoints
    path('quickbooks/auth/', qb.quickbooks_auth, name='quickbooks_auth'),
    path('quickbooks/callback/', qb.quickbooks_callback, name='quickbooks_callback'),
]

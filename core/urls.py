from django.urls import path
from . import views

urlpatterns = [
    path('api/get-site-id/', views.get_site_id, name='get_site_id'),
    path('api/get-drives/', views.get_drives, name='get_drives'),
    path('api/fetch-resumes/', views.fetch_resumes, name='fetch_resumes'),
    path('api/parse-resume/', views.parse_resume, name='parse_resume'),
    path('api/search-candidates/', views.search_candidates, name='search_candidates'),
    path('api/candidates/', views.list_candidates, name='list_candidates'),
]


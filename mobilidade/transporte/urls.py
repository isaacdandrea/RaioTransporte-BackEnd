# urls.py
from django.views.generic import TemplateView
urlpatterns = [
    path('api/alcance/', AlcanceAPIView.as_view()),
    path('', TemplateView.as_view(template_name='index.html')),  # React build
]

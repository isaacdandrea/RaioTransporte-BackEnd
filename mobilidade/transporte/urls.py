# transporte/urls.py

from django.urls import path
from django.views.generic import TemplateView
from .views import raio_de_alcance_view, AlcanceAPIView

urlpatterns = [
    path('api/alcance/', AlcanceAPIView.as_view(), name='alcance-api'),
    path('api/raio/', raio_de_alcance_view, name='raio-alcance'),
    path('', TemplateView.as_view(template_name='index.html')),
]

# transporte/urls.py

from django.urls import path
from django.views.generic import TemplateView

from .views import RaioDeAlcanceView

urlpatterns = [
    path('api/raio/', RaioDeAlcanceView.as_view(), name='raio-alcance'),
    path('', TemplateView.as_view(template_name='index.html')),
]

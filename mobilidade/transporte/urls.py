# transporte/urls.py

from django.urls import path

from .views import RaioDeAlcanceStreamView, RaioDeAlcanceView, RealTimeMonitorView

urlpatterns = [
    path('api/raio/', RaioDeAlcanceView.as_view(), name='raio-alcance'),
    path('api/raio/stream/', RaioDeAlcanceStreamView.as_view(), name='raio-alcance-stream'),
    path('', RealTimeMonitorView.as_view(), name='real-time-monitor'),
]

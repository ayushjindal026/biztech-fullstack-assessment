from django.urls import include, path
from orders.views import summary, broken_summary

urlpatterns = [
    path("api/orders/summary/", summary),
    path("api/orders/summary/broken/", broken_summary),
    path("silk/", include("silk.urls", namespace="silk")),
]

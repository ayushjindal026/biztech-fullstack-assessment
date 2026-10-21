from django.db.models import Prefetch
from django.http import JsonResponse
from .models import Order, OrderLine


def orders_queryset(optimized=True):
    qs = Order.objects.order_by("id")[:300]
    if optimized:
        qs = qs.select_related("customer").prefetch_related(
            Prefetch(
                "lines",
                queryset=OrderLine.objects.select_related("product").order_by("id"),
            )
        )
    return qs


def serialize(qs):
    return [
        {
            "id": o.id,
            "customer": o.customer.name,
            "lines": [
                {
                    "product": line.product.name,
                    "quantity": line.quantity,
                    "price": str(line.product.price),
                }
                for line in o.lines.all()
            ],
        }
        for o in qs
    ]


def summary(request):
    return JsonResponse({"orders": serialize(orders_queryset())})


def broken_summary(request):
    return JsonResponse({"orders": serialize(orders_queryset(False))})

from decimal import Decimal
from datetime import datetime, timezone
from django.db import connection
from django.core.management.color import no_style
from django.core.management.base import BaseCommand
from django.db import transaction
from orders.models import Customer, Product, Order, OrderLine


class Command(BaseCommand):
    help = "Replace demo orders with 320 deterministic orders (destructive to demo order data)."

    @transaction.atomic
    def handle(self, *args, **options):
        OrderLine.objects.all().delete()
        Order.objects.all().delete()
        Customer.objects.all().delete()
        Product.objects.all().delete()
        customers = [
            Customer.objects.create(id=i + 1, name=f"Customer {i:02}")
            for i in range(16)
        ]
        products = [
            Product.objects.create(
                id=i + 1, name=f"Product {i:02}", price=Decimal(i + 1)
            )
            for i in range(20)
        ]
        for i in range(320):
            order = Order.objects.create(id=i + 1, customer=customers[i % 16])
            OrderLine.objects.bulk_create(
                [
                    OrderLine(
                        id=i * 3 + j + 1,
                        order=order,
                        product=products[(i + j) % 20],
                        quantity=j + 1,
                    )
                    for j in range(3)
                ]
            )
        Order.objects.update(created_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
        # Explicit fixture IDs must not leave PostgreSQL sequences behind.
        with connection.cursor() as cursor:
            for sql in connection.ops.sequence_reset_sql(
                no_style(), [Customer, Product, Order, OrderLine]
            ):
                cursor.execute(sql)
        self.stdout.write("Created 320 orders, 960 lines.")

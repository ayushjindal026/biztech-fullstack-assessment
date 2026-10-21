from django.test import TestCase
from django.core.management import call_command
from .views import orders_queryset, serialize


class QueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_orders")

    def setUp(self):
        # Silk retains its thread-local collector after the test client request.
        from silk.collector import DataCollector

        DataCollector().clear()

    def test_reproduction(self):
        with self.assertNumQueries(1501):
            before = serialize(orders_queryset(False))
        with self.assertNumQueries(2):
            after = serialize(orders_queryset())
        self.assertEqual(before, after)
        self.assertEqual(len(after), 300)

    def test_constant_queries(self):
        for size in (1, 50, 300):
            with self.assertNumQueries(2):
                self.assertEqual(len(serialize(orders_queryset()[:size])), size)

    def test_endpoint(self):
        self.assertEqual(self.client.get("/api/orders/summary/").status_code, 200)

    def test_seed_is_repeatable(self):
        before = serialize(orders_queryset())
        call_command("seed_orders")
        self.assertEqual(before, serialize(orders_queryset()))

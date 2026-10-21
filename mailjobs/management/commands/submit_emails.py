from django.core.management.base import BaseCommand
from mailjobs.service import enqueue


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=500)

    def handle(self, *args, **options):
        for i in range(options["count"]):
            enqueue(
                f"customer{i}@example.test",
                "Order confirmation",
                "Your order is confirmed.",
            )
        self.stdout.write(f"Submitted {options['count']} durable jobs")

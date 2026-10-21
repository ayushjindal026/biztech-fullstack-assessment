from django.core.management.base import BaseCommand
from mailjobs.tasks import recover


class Command(BaseCommand):
    def handle(self, *args, **options):
        recover()

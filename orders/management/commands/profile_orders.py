import json
import platform
from pathlib import Path
from django.core.management.base import BaseCommand
from django.test import Client
from django.db import connection
from silk.models import Request


class Command(BaseCommand):
    help = "Generate genuine Silk request and SQL evidence from seeded data."

    def handle(self, *args, **options):
        result = {
            "python": platform.python_version(),
            "database": connection.vendor,
            "requests": [],
        }
        client = Client()
        for path in ("/api/orders/summary/broken/", "/api/orders/summary/"):
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            request = Request.objects.filter(path=path).latest("start_time")
            queries = list(
                request.queries.order_by("start_time").values("query", "time_taken")
            )
            result["requests"].append(
                {
                    "path": path,
                    "silk_request_id": str(request.pk),
                    "start_time": request.start_time.isoformat(),
                    "query_count": len(queries),
                    "silk_num_sql_queries": request.num_sql_queries,
                    "queries": queries,
                }
            )
        output = Path("evidence")
        output.mkdir(exist_ok=True)
        (output / "silk-profile.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        self.stdout.write(
            str([(r["path"], r["query_count"]) for r in result["requests"]])
        )

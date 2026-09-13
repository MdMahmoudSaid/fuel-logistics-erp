from django.db import connection
from django.http import JsonResponse

def readiness(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM django_migrations")
            if cursor.fetchone()[0] < 1:
                raise RuntimeError("schema unavailable")
        return JsonResponse({"status": "ok", "database": "ok"})
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)

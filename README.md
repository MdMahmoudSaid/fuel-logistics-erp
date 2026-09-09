# AZUR ÉNERGIE ERP

Internal ERP for a fuel trading and transport company operating between Senegal and Mali. Full business rules and data model live in [`docs/ERP_Specification.md`](docs/ERP_Specification.md); implementation is broken into phases in [`roadmap/`](roadmap/).

Stack: Django + Django REST Framework + PostgreSQL (`backend/`), Vue 3 + TypeScript (`frontend/`).

## Quickstart (Docker)

```bash
cp .env.example .env   # adjust if needed, defaults work for local dev
docker compose up --build
```

- Backend API: http://localhost:8000/api/ (docs at `/api/docs/`)
- Frontend: http://localhost:5173
- Postgres: localhost:5432

Migrations run automatically when the `backend` container starts. To create an admin user:

```bash
docker compose exec backend python manage.py createsuperuser
```

## Production deployment (Docker)

```bash
cp .env.prod.example .env   # fill in real secrets — see comments in the file
docker compose -f docker-compose.prod.yml up --build -d
```

This runs Postgres (data persisted in the `postgres_data` volume, not exposed on the host), the Django API under Gunicorn (`config.settings.prod`), and the built Vue app served by Nginx. Migrations and `collectstatic` run automatically on `backend` startup. Create an admin user the same way as in dev:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

`docker-compose.prod.yml` covers the app + database only — a reverse proxy/TLS termination in front of it (e.g. Caddy or Nginx on the host) and scheduled backups are tracked separately in [`roadmap/phase_7_hardening_deployment.md`](roadmap/phase_7_hardening_deployment.md) and not set up here.

## Quickstart (without Docker)

**Backend**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py runserver
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

## Tests

```bash
# Backend
cd backend && pytest

# Frontend
cd frontend && npm run test:unit
```

## Project layout

```
backend/    Django + DRF API (apps/ holds one Django app per domain area)
frontend/   Vue 3 + TypeScript app (src/modules/ holds one folder per feature area)
docs/       ERP_Specification.md — the source of truth for business rules
roadmap/    Phase-by-phase implementation plan (phase_1_foundation.md ... phase_7_hardening_deployment.md)
```

## Development phases

See `roadmap/` for the full breakdown. Build order: Foundation → Purchasing → Truck Operations → Delivery & Sales → Finance → Management → Production Hardening. Each phase file lists its models, API endpoints, Vue components, and mandatory integration tests.

# Phase 7 — Production Hardening

Spec reference: `docs/ERP_Specification.md` §46 (Phase 7), §40–41, §45, §47–48.

## Goal

No new domain models or business logic — this phase makes the system safe and usable in the field: responsive/mobile polish, weak-internet tolerance, security hardening, backups, and a full regression pass against every mandatory test and acceptance criterion from §47–48 before calling V1 done.

## Work items (no new "Models" section — infrastructure/config/tests only)

**Responsive & PWA (§40)**
- Audit every Vue view built in Phases 1–6 at phone/tablet breakpoints; fix any table/form that doesn't degrade gracefully (card-based layout for lists on narrow screens is preferable to horizontal scroll).
- Complete the PWA manifest + service worker scaffolded in the initial setup: offline app-shell caching, install prompt.

**Weak-internet handling (§41)**
- Axios interceptor: automatic retry with backoff on network failure for idempotent GET requests.
- Local draft persistence (e.g. form state in `localStorage`) for in-progress creates (trip loading forms, delivery control forms) so a dropped connection doesn't lose field input.
- Explicit offline queue for a *narrow, whitelisted* set of non-financial actions only (e.g. status notes) — financial validation (payments, invoices, expenses) must still require a live server round-trip per §41, never queued client-side.

**Security**
- Full audit of `Role` permission flags vs. every DRF view's declared permission class — no endpoint should fall through to "authenticated = allowed."
- CORS/CSRF configuration reviewed for the production frontend origin.
- Secrets (Django `SECRET_KEY`, DB credentials, JWT signing key) sourced only from environment/`.env`, never committed; rotate the dev-scaffold placeholder values before go-live.
- Rate limiting on `/api/auth/login/`.
- Dependency vulnerability scan (`pip-audit`, `npm audit`) clean or explicitly triaged.

**Backups**
- Scheduled `pg_dump` job (cron or equivalent) with retention policy and a documented restore procedure — actually test the restore once, not just the backup.

**Deployment**
- Production `docker-compose.prod.yml` (or equivalent): Gunicorn/Uvicorn for Django, Nginx serving the built Vue bundle + reverse-proxying `/api/`, TLS termination.
- CI pipeline: lint (`ruff`, `eslint`) + test (`pytest`, `vitest`) on every push, blocking merge on failure.

**Explicitly out of scope** (§45 — do not build unless separately approved): shareholder management, profit distribution, fiscal-year closing, advanced accounting journal, advanced bank reconciliation, full offline sync engine, AI features, GPS tracking, WhatsApp automation, predictive analytics, native desktop apps.

## Mandatory Integration Tests — full §47 regression suite

Every test below must exist as an automated integration test (most were introduced in earlier phases; this phase's job is to confirm the *full set* passes together against a realistic combined fixture, not introduce them for the first time):

1. Multiple Trucks — one order, 10 different trucks.
2. Repeated Truck — one truck, two separate trips against the same order.
3. Partial Delivery — order delivered over several days.
4. Quantity Loss — 45,000 loaded → 44,850 received.
5. Transport Deduction — loss above tolerance reduces transporter balance correctly.
6. Partial Customer Payment — invoice paid in several installments.
7. Transporter Advance — advance deducted correctly from outstanding.
8. Supplier Reliquat — unloaded purchased fuel remains available.
9. Customer Indirect Payment — customer pays customs directly, bank balance unaffected.
10. Financial Transfer — bank-to-bank transfer excluded from profit.
11. Margin — new expense post-delivery changes trip margin automatically.

## Definition of Done — full §48 acceptance checklist

Run through all 27 items in §48 end-to-end (not unit-tested in isolation — actually perform the workflow through the UI against a staging deployment) and sign off each as pass/fail before declaring V1 complete. Any failure blocks release; do not ship with a known-broken acceptance item.

# Phase 1 — Foundation

Spec reference: `docs/ERP_Specification.md` §46 (Phase 1), §4, §8–10, §18, §28, §38.

## Goal

Stand up authentication, role-based permissions, and every master-data entity that later phases attach records to: users, products, suppliers, customers, transporters, drivers, trucks, banks, cash accounts. No transactional/financial logic yet — this phase is pure reference data + access control.

## Models (`backend/apps/accounts`, `core`, `suppliers`, `customers`, `transport`, `finance`)

**`User`** (custom, `AUTH_USER_MODEL`) — `email` (unique, login field), `full_name`, `phone`, `role` (FK → `Role`), `is_active`, `date_joined`, `last_login`.

**`Role`** — `name`, and a permission flag per module × action, e.g. `can_view_operations`, `can_create_operations`, `can_edit_operations`, `can_validate_operations`, `can_cancel_operations`, `can_export_operations`, repeated for `finance`, `sales`, `purchasing`, `admin` modules (§38: View/Create/Edit/Validate/Cancel/Export). Seed the four initial roles (Admin, Management, Operations, Finance) via a data migration, not hardcoded in views.

**`Product`** — `name`, `code`, `is_active`. Seed Gasoil and Essence via data migration (§5: "additional products can be added later").

**`Supplier`** — `name`, `company_name`, `country`, `phone`, `contact_name`, `notes`, `is_active`. (Purchase history, payments, advances, outstanding are all *derived* in Phase 2/5 — no denormalized balance fields here.)

**`Customer`** — `name`, `company_name`, `phone`, `address`, `contact_name`, `notes`, `is_active`.

**`Transporter`** — `name`, `company_name`, `phone`, `address`, `is_active`.

**`Driver`** — `name`, `phone`, `license_number`, `notes`. All fields except `name` optional (§10: "a missing driver must not block operations"). No FK to a single truck — drivers are assigned per-trip in Phase 3.

**`Truck`** — `internal_id` (unique, human-readable), `tractor_registration`, `tanker_registration`, `capacity_litres`, `ownership_type` (`COMPANY_OWNED` / `EXTERNAL`), `owner_transporter` (FK → `Transporter`, null if company-owned), `default_driver` (FK → `Driver`, nullable), `status` (`AVAILABLE` / `ON_TRIP` / `BLOCKED`), `notes`. `status` is authoritative only from Phase 3 onward (trip creation flips it); in Phase 1 it just needs to exist and default to `AVAILABLE`.

**`BankAccount`** — `name`, `bank_name`, `account_number`, `currency` (choices, default `XOF`), `opening_balance`, `is_active`. `current_balance` is a computed property (opening balance + Σ treasury transactions), not a stored field — avoids drift, recalculated in Phase 5.

**`CashAccount`** — `name`, `location`, `currency` (default `XOF`), `opening_balance`, `is_active`. Same computed-balance rule as `BankAccount`.

All models inherit a shared `TimeStampedModel` abstract base (`created_at`, `updated_at`) from `core`.

## API Endpoints

- `POST /api/auth/login/` — issue JWT pair (simplejwt)
- `POST /api/auth/refresh/`
- `GET /api/auth/me/` — current user + role + permission flags
- `GET|POST /api/users/`, `GET|PATCH|DELETE /api/users/{id}/` (Admin only for create/edit)
- `GET|POST /api/roles/`, `GET|PATCH /api/roles/{id}/`
- `GET|POST /api/products/`, `GET|PATCH /api/products/{id}/`
- `GET|POST /api/suppliers/`, `GET|PATCH /api/suppliers/{id}/`
- `GET|POST /api/customers/`, `GET|PATCH /api/customers/{id}/`
- `GET|POST /api/transporters/`, `GET|PATCH /api/transporters/{id}/`
- `GET|POST /api/drivers/`, `GET|PATCH /api/drivers/{id}/`
- `GET|POST /api/trucks/`, `GET|PATCH /api/trucks/{id}/`
- `GET|POST /api/bank-accounts/`, `GET|PATCH /api/bank-accounts/{id}/`
- `GET|POST /api/cash-accounts/`, `GET|PATCH /api/cash-accounts/{id}/`

All list endpoints support `?search=` and pagination. Write access gated by `Role` permission flags via a shared DRF permission class (`HasModulePermission`), not per-view hardcoded checks.

## Vue Components (`frontend/src/modules/...`)

- `auth/LoginView.vue`, `auth/store.ts` (Pinia)
- `shell/AppShell.vue` — nav shell, role-aware menu
- `users/UserList.vue`, `users/UserForm.vue`, `roles/RoleForm.vue` (permission matrix editor)
- `products/ProductList.vue`, `ProductForm.vue`
- `suppliers/SupplierList.vue`, `SupplierForm.vue`
- `customers/CustomerList.vue`, `CustomerForm.vue`
- `transporters/TransporterList.vue`, `TransporterForm.vue`
- `drivers/DriverList.vue`, `DriverForm.vue`
- `trucks/TruckList.vue`, `TruckForm.vue`
- `finance/BankAccountList.vue`, `BankAccountForm.vue`, `CashAccountList.vue`, `CashAccountForm.vue`

Shared: a generic `DataTable` + `EntityForm` pattern reused across all master-data modules rather than one-off implementations per entity.

## Mandatory Integration Tests

- Login with valid/invalid credentials; token refresh; `me` reflects correct role and permissions.
- A user with `Operations` role can create a `Truck` but is denied creating a `BankAccount` (403).
- CRUD round-trip for each master entity (create → list → retrieve → update).
- Driver creation with only `name` set succeeds (optional-field rule from §10).
- Product seed data present after migration (Gasoil, Essence).

## Definition of Done (§48 acceptance criteria covered)

- #5 "Register trucks and transporters" — data model + CRUD in place.
- #27 "Use the system securely from computer and phone" — auth + responsive shell working end-to-end (full responsiveness polish is Phase 7).

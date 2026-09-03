# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`truck_service_center` is a **Frappe app that depends on ERPNext** (`required_apps = ["erpnext"]` in [hooks.py](truck_service_center/hooks.py)). It manages a truck service-center business: vehicles, service appointments, work orders, repair quotations, and service packages. It is **not** a standalone Python package — it runs inside a Frappe bench and reuses ERPNext's `Item`, `Warehouse`, `Customer`, `Stock Entry`, and `Sales Invoice`. Most of it is desk UI, with one exception: technicians work from a mobile/tablet **website portal** at `/service-order-portal` (see **Technician portal** below).

Domain docs (read these first for the business model): [DOCTYPES_README.md](DOCTYPES_README.md) and [SETTINGS_README.md](SETTINGS_README.md). Both are written in Thai, as is most of the in-app UI text.

## Commands

All `bench` commands run from the bench directory (`../../` relative to this app, i.e. `frappe-bench/`), not from the app root. The dev site here is **`bu3.localhost`** with `developer_mode = 1`.

```bash
# from frappe-bench/
bench --site bu3.localhost migrate              # apply schema + import standard records
bench --site bu3.localhost clear-cache          # after editing workspaces/fixtures/boot data
bench --site bu3.localhost console               # interactive python REPL with frappe loaded
bench build --app truck_service_center           # rebuild JS/CSS assets

# Tests (Frappe test runner; site_config needs "allow_tests": true — already set on bu3)
bench --site bu3.localhost run-tests --app truck_service_center
bench --site bu3.localhost run-tests --doctype "Service Order"     # single doctype
bench --site bu3.localhost run-tests --module truck_service_center.truck_service_center.doctype.service_order.test_service_order
```

The money-calculation tests (`test_service_order.py`, `test_repair_quotation.py`) build **unsaved** docs and call `calculate_totals()` / `calculate_wht()` directly — deliberately no `insert()`, because saving triggers `fetch_from` which overwrites child `labor_charges` from the Service Type master, and `IntegrationTestCase`'s auto test-record loading collides with real site data (Price List "Standard Buying" already exists). Use `UnitTestCase` for this kind of test.

Lint/format is via **pre-commit** (run from the app root), configured in [.pre-commit-config.yaml](.pre-commit-config.yaml): ruff (lint + format, line-length 110), eslint, prettier, pyupgrade.

```bash
cd apps/truck_service_center && pre-commit install   # one-time
pre-commit run --all-files
```

## Architecture

### Document flow
The core is a three-stage pipeline, each stage a submittable doctype with parallel child-table structure:

**Service Appointment** (booking) → **Service Order** (the work, the central doc) → **Repair Quotation** (estimate). Each parent has a matching set of child tables following the same shape:
- `*_service_type` — labor lines (pulls labor rate / time / PM-CM type from `Service Type`)
- `*_item` — parts lines (links ERPNext `Item`, drives stock issue)
- `*_package` — applied `Service Package`

`Service Package` bundles service types + parts at a discounted rate; selecting one on a Service Order auto-loads its lines.

### Parts provenance and cascade delete
Every parts row on all three transaction doctypes carries **two** provenance fields — `service_package` and `service_type` — and both cascade on delete: removing a package drops the service types and parts it brought in (`service_packages_remove` in each doctype's js, mirrored at the top of `apply_service_packages()` on Service Order and Repair Quotation), and removing a single service type drops the parts pulled from that service type (`remove_orphan_service_type_items`, likewise in all three js files and in the Service Order / Repair Quotation controllers). Service Appointment applies packages client-side only, so its cascade is client-side only too. A row whose `service_type` is blank counts as hand-added and is never cascaded — that includes every parts row created before the field existed, which was deliberately left un-backfilled. On Service Order a row with a **submitted** `material_issue` is also never removed; the issue must be cancelled first.

Removing the *service type* in that situation is blocked outright, otherwise the issued part would survive as a row with no provenance and the order would stop matching its stock entry. `validate_service_type_removal()` is the real gate — it diffs against `get_doc_before_save()` and throws, so it also covers removing the **package** (which takes its service types with it) and any save that comes through the API. It asks the Stock Entry for its `docstatus` rather than trusting the row's cached `material_issue_status`, because `update_material_issue_status()` only refreshes that at the end of `validate()`. `before_service_types_remove` in service_order.js is the friendly client-side half; note it must return a **rejected promise** to actually stop the deletion — `grid_row.remove()` chains the `before_*_remove` trigger through `frappe.run_serially` and only checks whether the chain rejected, so `return false` does nothing.

Because of that, parts pulled from a service type are always appended as **new rows**, never merged into an existing row with the same `item_code`. Merging would make a row's provenance ambiguous and there would be no correct quantity to remove later. Expect to see the same item on several rows.

`apply_service_packages()` decides a package is already loaded by looking for its `service_package` in **both** child tables. Checking only `service_types` (as it originally did) meant deleting a package's service types while keeping the package row made the next save re-import the whole package, doubling its parts.

### Master data
`Service Type` (grouped by `Service Type Group`, tagged PM/CM), `Repair Position`, `Vehicle`, `Vehicle Brand`, `Service Appointment Slot`. Standard rows are seeded from scripts: [setup_appointment_slots.py](truck_service_center/setup_appointment_slots.py) and the scripts under [truck_service_center/fixtures/](truck_service_center/fixtures/) (`create_service_type_groups.py`, `repair_position_data.py`).

`Vehicle Brand` is a creatable list of vehicle makes (field `brand_name`). The `brand` field on `Vehicle` is a `Link` to it, so new brands can be added inline from the form. Default brands (truck makes sold in Thailand — Isuzu, Hino, Mitsubishi Fuso, UD Trucks, etc.) are seeded by `create_default_vehicle_brands()` in [install.py](truck_service_center/install.py).

> Note: ERPNext also ships a doctype named `Vehicle` (module Setup). The name collides — this app's `Vehicle` (module Truck Service Center) wins because it imports after ERPNext on `migrate`. Avoid hand-running `reload-doc` on ERPNext's `vehicle.json`; it overwrites the DB `Vehicle` with the wrong version.

### Installation / seeding
`after_install` ([hooks.py](truck_service_center/hooks.py) → [install.py](truck_service_center/install.py)) seeds default `Vehicle Brand` records, the app's roles (`Service Manager`, `Service User`, `Technician`, `Technician Manager` — see the permission matrix in [DOCTYPES_README.md](DOCTYPES_README.md)), and the `Technician` / `Technician Manager` **Role Profiles** that make those roles selectable when creating a User. `after_install` does **not** run on existing sites — seed those manually: `bench --site bu3.localhost execute truck_service_center.install.create_default_vehicle_brands`. Every seeder is idempotent (brands skip what exists; the role-profile seeder tops up missing roles without dropping hand-added ones). Anything appended to `DEFAULT_ROLES` / `DEFAULT_ROLE_PROFILES` later only reaches existing sites through a patch — that is what `create_technician_manager_role` and `create_technician_role_profiles` in [patches.txt](truck_service_center/patches.txt) exist for.

### ERPNext integration (lives in Service Order controller)
Parts leave stock through a **Stock Entry** of type Material Issue, created only by the "Create Material Issue" button on a draft Service Order (whitelisted `create_material_issue`) and only after the vehicle has been received (see **Receive-vehicle gate** below) — there is no auto-creation on submit. Each parts row carries `material_issue` / `material_issue_status`, and the order cannot be submitted until every stock item has a submitted issue. `doc_events` on Stock Entry submit+cancel write the status straight back to the child rows; cancelling an issue also clears the link so the row can be re-issued. Two custom fields ship with the app via `create_custom_fields()` in [install.py](truck_service_center/install.py) — `Stock Entry.custom_service_order` links back to the order, and `Stock Entry Detail.custom_service_order_item` holds the child row name that the Sync button matches on (never match on row index — it shifts when rows are deleted). Note the back-link means a Service Order with a submitted issue cannot be cancelled until the issue is. When syncing an issue back, never copy `basic_rate` into the row's `rate`: ERPNext overwrites it with the valuation rate on every save, so it would replace the selling price with cost.

On submit, Service Order can auto-create a **Sales Invoice** (labor billed via a dedicated "Labor Item"). Payments flow through **Payment Entry**: the "รับชำระเงิน" button creates a draft PE against the linked Sales Invoice, and `doc_events` in [hooks.py](truck_service_center/hooks.py) (Payment Entry / Journal Entry / Sales Invoice submit+cancel) sync `paid_amount` / `outstanding_amount` / `payment_status` back onto the Service Order — those three fields are read-only and must never be set by hand.

Thai invoices must show exact totals (no rounding): `create_sales_invoice` forces `disable_rounded_total = 1` on the Sales Invoice, and sites should also tick Global Defaults → Disable Rounded Total (see SETTINGS_README "วิธีตั้งค่าครั้งแรก"). The payment-status sync and the WHT full-outstanding check still read `rounded_total or grand_total` to stay correct for legacy invoices created while rounding was on.

Thai **withholding tax (หัก ณ ที่จ่าย, default 3%)**: corporate customers withhold WHT on the service portion at payment time. `calculate_wht()` computes `wht_amount` on the pre-VAT base (labor-only proportional share by default, whole bill for lump-sum jobs; document discount allocated proportionally; VAT stripped for VAT-inclusive orders), mirrored client-side in `calculate_wht` in service_order.js — keep both in sync. The Sales Invoice stays at full value; `create_payment_entry` reduces the received amount and books the difference to Settings `wht_account` via a PE deductions row (requires `default_cost_center`). Auto-skipped with a warning when the invoice already has partial payments. All of this is **driven by the `Truck Service Center Settings` singleton** — default company/warehouse, labor item & expense account, auto-create-stock-entry toggle, auto-submit-invoice toggle, invoice series. Behavior changes when those settings change; check the singleton before debugging missing stock entries / invoices (see [SETTINGS_README.md](SETTINGS_README.md)).

### Receive-vehicle gate (Service Order controller)
"รับรถ" is `receive_vehicle`, which stamps `received_by` / `received_date` and moves Draft → In Progress. Two rules hang off that stamp:
- **No parts issue before the vehicle is received.** `create_material_issue` throws unless the order has a `received_date` *or* is already `In Progress` — the second clause is there because records predating the rule changed status by hand and never got a stamp. The desk button in `service_order.js` is hidden under the same condition, but the server check is the real gate (it also covers the auto-create prompt raised during submit validation).
- **Any transition into `In Progress` counts as receiving.** `status` is a plain Select a user can edit by hand, so `stamp_receive_on_progress()` in `validate()` fills `received_by` / `received_date` whenever the status changes to In Progress and no stamp exists. It never overwrites an existing stamp (`receive_vehicle` writes before calling `save()`), and it only fires when `status` actually changed — otherwise long-standing In-Progress records would get a bogus timestamp the next time someone saved something unrelated.

`set_address_display()` recomputes only when the address field itself changed. That is a **permission** guard, not an optimization: `get_address_display()` calls `Address.check_permission()`, and Frappe's hook for Address delegates to the linked party doctype. `Technician` has no read on `Customer`, so recomputing on every save made technicians unable to save *any* order carrying a `customer_address` — through the portal and through the desk alike, with a bare `PermissionError` and no useful message.

### Technician portal (website pages, not desk)
Technicians work from `/service-order-portal` rather than the desk. Three moving parts:

**Routing** — `role_home_page` in [hooks.py](truck_service_center/hooks.py) sends both `Technician` and `Technician Manager` to `service-order-portal` after login instead of `/app`; `website_route_rules` maps `/service-order-portal/<name>` to the `service-order-job` template, landing the order name in `frappe.form_dict.name`.

**Pages** — [truck_service_center/www/](truck_service_center/www/) holds the job list (`service-order-portal.html` + `service_order_portal.py`) and the job detail (`service-order-job.html` + `service_order_job.py`). Both guard with `frappe.throw(..., frappe.PermissionError)`, which Frappe renders as a Not Permitted page whose Login button already carries `?redirect-to=` — never hand-build that redirect. Both set `no_cache = 1`, which is what makes the refresh button a plain `location.reload()`. All CSS and JS is inline in the templates and nothing lives under `public/`, so **`bench build` is never needed** for the portal. The UI is deliberately button-driven for gloved hands on a tablet (fuel level as five buttons, working time as a ±0.5h stepper debounced 800 ms before saving, canned remark chips); mileage is the only field that requires typing.

**Writes** — [truck_service_center/api/technician_portal.py](truck_service_center/api/technician_portal.py) exposes five narrow whitelisted endpoints (fuel level, actual time, mileage, remarks, status) instead of a generic doctype write. All of them funnel through `_get_editable_job()`, which checks, in order: doctype `write` permission → the session user is named in one of the four technician fields (or holds a `MANAGER_ROLES` role) → `docstatus == 0` and the status is still open. `set_status` permits only the transitions in `ALLOWED_TRANSITIONS` and hands Draft → In Progress to the controller's `receive_vehicle`, so the fuel-in requirement and the receive stamp still apply.

**Closing a job** — `set_status(..., "Completed")` runs `_validate_completion()` first: `actual_time > 0` and `fuel_level_out` must both be set. Both are hard server-side gates, because `Completed` falls outside `EDITABLE_STATUSES`, so a technician who closes a job cannot reopen or amend it from the portal — the manager has to fix it in the desk. `actual_time` duplicates a `before_submit` rule deliberately, moving it earlier to where the technician can still act on it. **Mileage is not a gate**, only a confirm: `_build_job_view()` passes `vehicle_mileage` (the Vehicle's own `current_mileage`, which is the value pre-filled into a new order), and the page asks for confirmation when the order's mileage still equals it or is blank — i.e. nobody recorded a reading this visit. That comparison is what makes the nag survive a reload; a "did the field change on screen" check would not. The page also refuses to close while a value is typed-but-unsaved: `savedTime` / `savedMileage` track what the server acknowledged, so the 800 ms working-time debounce and the manual mileage save button cannot silently lose an edit behind the status change.

**Scoping** — a plain `Technician` sees only orders where they occupy one of `technician` / `technician_2` / `technician_3` / `technician_4`. That is a flat four-field design rather than a child table, so the query needs `or_filters` (Frappe wraps those in a single parenthesised OR group and ANDs it with `filters`). Roles in `MANAGER_ROLES` — `Technician Manager`, `Service Manager`, `System Manager` — see every open order and may edit any of them, and the list then renders an extra "ช่าง" row per card. This scoping is **presentation only**: Service Order has no `permission_query_conditions` hook, so a technician can still read every order through the desk or the REST API. Hardening means adding that hook plus a `has_permission` one, then switching the portal queries from `frappe.get_all` to `frappe.get_list` and deleting the manual filter.

Portal gotchas, all of which cost time once:
- **A `www` page and its Python module must be flat files, and the `.py` uses underscores where the `.html` uses hyphens** (`service-order-job.html` ↔ `service_order_job.py`). `set_pymodule()` swaps hyphens for underscores in the *basename* only, so a `www/service-order-job/index.py` directory layout yields an unimportable dotted path. `www/__init__.py` is required.
- **Never name a template context key `items`.** The view objects are `frappe._dict`, a dict subclass, so `job.items` resolves to the bound `dict.items` method and Jinja dies with `object of type 'builtin_function_or_method' has no len()`. The parts list is called `parts` for exactly this reason.
- `User.default_workspace` **silently overrides `role_home_page`** (`frappe/website/utils.py` returns a workspace URL and short-circuits). A technician with that field set never reaches the portal.
- An **already logged-in** System User who opens `/login` is sent to `/desk`, not the portal — `frappe/www/login.py` hardcodes it. The role redirect only fires on a genuine login.
- `get_home_page()` caches per user in redis unless the **`DEV_SERVER` env var** is set (`developer_mode` in site_config is *not* enough — `bench console` does not set it, `bench serve` does), so run `bench clear-cache` after touching the hook and don't trust a console reading.

### Reports
Four Script Reports under [truck_service_center/report/](truck_service_center/truck_service_center/report/) (Vehicle Service History, Revenue by Service Group, Customer Outstanding Summary, Technician Performance) — English report names, Thai column labels/filters (filters live in the `.js` files). They're surfaced via a "รายงาน" section in both the workspace content/shortcuts and the Workspace Sidebar (see the Workspace & Sidebar gotchas below). Revenue/outstanding numbers come from Service Order fields, not GL entries.

### Scheduled tasks
`scheduler_events` (daily, [hooks.py](truck_service_center/hooks.py) → [tasks.py](truck_service_center/tasks.py)): expire stale Repair Quotations, and notify Service Manager/Service User (via Notification Log) about vehicle document expirations and service-due vehicles. Toggles + notice windows live in the Settings singleton (defaults seeded by the `set_notification_defaults` patch). Gotcha: unset Check/Int fields on a Single read back as `0` through both `frappe.get_single` and `frappe.db.get_single_value` — to distinguish "never set" from "intentionally off", read the raw `tabSingles` row (see `_setting_enabled`). Another gotcha: date filters like `["<=", cutoff]` become `ifnull(field, '') <= cutoff` in SQL, so rows with NULL dates match — always pair with `["is", "set"]`.

### Exported fixtures
[hooks.py](truck_service_center/hooks.py) `fixtures` exports specific `Print Format` (Service Order, Sale Invoice (Truck Service), Repair Quotation) and `Letter Head` (LINE-LETTER-HEAD) records. The JSON lives in [truck_service_center/fixtures/](truck_service_center/fixtures/) and is re-imported on `migrate`.

## Workspace & Sidebar (Frappe v17) — gotchas

The desk navigation has two independent pieces; editing one does not affect the other:

1. **Workspace** ([truck_service_center/workspace/truck_service_center/](truck_service_center/truck_service_center/workspace/truck_service_center/)) — the page content (header/shortcut/paragraph/spacer blocks in the `content` field) plus its `shortcuts`/`links`. Section headers in the page body should all use the same block `type: "header"` with `<span class="h4"><b>…</b></span>`; a `paragraph` block renders smaller/greyer and looks inconsistent. **The visible page body renders from `shortcut` blocks in `content` (each referencing a row in the `shortcuts` array by `shortcut_name`), NOT from the `links` array.** To add a card under a section (e.g. "Master Data"), add a `shortcuts` row **and** insert a `shortcut` block in `content` after that section's header — adding only a `links` entry shows nothing on the page.

2. **Workspace Sidebar** (doctype, exported to [truck_service_center/workspace_sidebar/](truck_service_center/workspace_sidebar/)) — the **left sidebar is built from this, NOT from the workspace's links and NOT from child workspaces / `parent_page`** (that was the pre-v17 model and does nothing in v17). Grouping is done inside its `items` child table: an item with `type: "Section Break"` starts a collapsible group, and the items after it with `child: 1` are nested under it. Icons are **lucide** names (verify against `apps/frappe/frappe/public/icons/lucide.svg`; e.g. `house`, not `home`). A `Workspace Sidebar` is auto-generated from a workspace's shortcuts on `migrate` with `standard: 0, app: null` (DB-only). To version it in this app, set `app: "truck_service_center"` and `standard: 1` and save — with `developer_mode` on, `before_save` exports it to `workspace_sidebar/<scrubbed_title>.json`.

3. **`reload-doc` / `migrate` only re-import a record file when its `modified` timestamp is newer than the DB row.** After hand-editing any standard-record JSON (workspace, workspace_sidebar, etc.), bump the `modified` field or the import is silently skipped. Then `clear-cache` and hard-refresh the browser (boot data is cached client-side).

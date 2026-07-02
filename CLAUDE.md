# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`truck_service_center` is a **Frappe app that depends on ERPNext** (`required_apps = ["erpnext"]` in [hooks.py](truck_service_center/hooks.py)). It manages a truck service-center business: vehicles, service appointments, work orders, repair quotations, and service packages. It is **not** a standalone Python package — it runs inside a Frappe bench and reuses ERPNext's `Item`, `Warehouse`, `Customer`, `Stock Entry`, and `Sales Invoice`.

Domain docs (read these first for the business model): [DOCTYPES_README.md](DOCTYPES_README.md) and [SETTINGS_README.md](SETTINGS_README.md). Both are written in Thai, as is most of the in-app UI text.

## Commands

All `bench` commands run from the bench directory (`../../` relative to this app, i.e. `frappe-bench/`), not from the app root. The dev site here is **`bu3.localhost`** with `developer_mode = 1`.

```bash
# from frappe-bench/
bench --site bu3.localhost migrate              # apply schema + import standard records
bench --site bu3.localhost clear-cache          # after editing workspaces/fixtures/boot data
bench --site bu3.localhost console               # interactive python REPL with frappe loaded
bench build --app truck_service_center           # rebuild JS/CSS assets

# Tests (Frappe test runner)
bench --site bu3.localhost run-tests --app truck_service_center
bench --site bu3.localhost run-tests --doctype "Service Order"     # single doctype
bench --site bu3.localhost run-tests --module truck_service_center.truck_service_center.doctype.service_order.test_service_order
```

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

### Master data
`Service Type` (grouped by `Service Type Group`, tagged PM/CM), `Repair Position`, `Vehicle`, `Vehicle Brand`, `Service Appointment Slot`. Standard rows are seeded from scripts: [setup_appointment_slots.py](truck_service_center/setup_appointment_slots.py) and the scripts under [truck_service_center/fixtures/](truck_service_center/fixtures/) (`create_service_type_groups.py`, `repair_position_data.py`).

`Vehicle Brand` is a creatable list of vehicle makes (field `brand_name`). The `brand` field on `Vehicle` is a `Link` to it, so new brands can be added inline from the form. Default brands (truck makes sold in Thailand — Isuzu, Hino, Mitsubishi Fuso, UD Trucks, etc.) are seeded by `create_default_vehicle_brands()` in [install.py](truck_service_center/install.py).

> Note: ERPNext also ships a doctype named `Vehicle` (module Setup). The name collides — this app's `Vehicle` (module Truck Service Center) wins because it imports after ERPNext on `migrate`. Avoid hand-running `reload-doc` on ERPNext's `vehicle.json`; it overwrites the DB `Vehicle` with the wrong version.

### Installation / seeding
`after_install` ([hooks.py](truck_service_center/hooks.py) → [install.py](truck_service_center/install.py)) seeds default `Vehicle Brand` records and the app's roles (`Service Manager`, `Service User`, `Technician` — see the permission matrix in [DOCTYPES_README.md](DOCTYPES_README.md)) on fresh install. `after_install` does **not** run on existing sites — seed those manually: `bench --site bu3.localhost execute truck_service_center.install.create_default_vehicle_brands`. The seeder is idempotent (skips brands that already exist).

### ERPNext integration (lives in Service Order controller)
On submit, Service Order can auto-create a **Stock Entry** (issues parts from a warehouse) and a **Sales Invoice** (labor billed via a dedicated "Labor Item"). Payments flow through **Payment Entry**: the "รับชำระเงิน" button creates a draft PE against the linked Sales Invoice, and `doc_events` in [hooks.py](truck_service_center/hooks.py) (Payment Entry / Journal Entry / Sales Invoice submit+cancel) sync `paid_amount` / `outstanding_amount` / `payment_status` back onto the Service Order — those three fields are read-only and must never be set by hand.

Thai **withholding tax (หัก ณ ที่จ่าย, default 3%)**: corporate customers withhold WHT on the service portion at payment time. `calculate_wht()` computes `wht_amount` on the pre-VAT base (labor-only proportional share by default, whole bill for lump-sum jobs; document discount allocated proportionally; VAT stripped for VAT-inclusive orders), mirrored client-side in `calculate_wht` in service_order.js — keep both in sync. The Sales Invoice stays at full value; `create_payment_entry` reduces the received amount and books the difference to Settings `wht_account` via a PE deductions row (requires `default_cost_center`). Auto-skipped with a warning when the invoice already has partial payments. All of this is **driven by the `Truck Service Center Settings` singleton** — default company/warehouse, labor item & expense account, auto-create-stock-entry toggle, auto-submit-invoice toggle, invoice series. Behavior changes when those settings change; check the singleton before debugging missing stock entries / invoices (see [SETTINGS_README.md](SETTINGS_README.md)).

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

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
`Service Type` (grouped by `Service Type Group`, tagged PM/CM), `Repair Position`, `Vehicle`, `Service Appointment Slot`. Standard rows are seeded from scripts: [setup_appointment_slots.py](truck_service_center/setup_appointment_slots.py) and the scripts under [truck_service_center/fixtures/](truck_service_center/fixtures/) (`create_service_type_groups.py`, `repair_position_data.py`).

### ERPNext integration (lives in Service Order controller)
On submit, Service Order can auto-create a **Stock Entry** (issues parts from a warehouse) and a **Sales Invoice** (labor billed via a dedicated "Labor Item"). All of this is **driven by the `Truck Service Center Settings` singleton** — default company/warehouse, labor item & expense account, auto-create-stock-entry toggle, auto-submit-invoice toggle, invoice series. Behavior changes when those settings change; check the singleton before debugging missing stock entries / invoices (see [SETTINGS_README.md](SETTINGS_README.md)).

### Exported fixtures
[hooks.py](truck_service_center/hooks.py) `fixtures` exports specific `Print Format` (Service Order, Sale Invoice (Truck Service), Repair Quotation) and `Letter Head` (LINE-LETTER-HEAD) records. The JSON lives in [truck_service_center/fixtures/](truck_service_center/fixtures/) and is re-imported on `migrate`.

## Workspace & Sidebar (Frappe v17) — gotchas

The desk navigation has two independent pieces; editing one does not affect the other:

1. **Workspace** ([truck_service_center/workspace/truck_service_center/](truck_service_center/truck_service_center/workspace/truck_service_center/)) — the page content (header/shortcut/paragraph/spacer blocks in the `content` field) plus its `shortcuts`/`links`. Section headers in the page body should all use the same block `type: "header"` with `<span class="h4"><b>…</b></span>`; a `paragraph` block renders smaller/greyer and looks inconsistent.

2. **Workspace Sidebar** (doctype, exported to [truck_service_center/workspace_sidebar/](truck_service_center/workspace_sidebar/)) — the **left sidebar is built from this, NOT from the workspace's links and NOT from child workspaces / `parent_page`** (that was the pre-v17 model and does nothing in v17). Grouping is done inside its `items` child table: an item with `type: "Section Break"` starts a collapsible group, and the items after it with `child: 1` are nested under it. Icons are **lucide** names (verify against `apps/frappe/frappe/public/icons/lucide.svg`; e.g. `house`, not `home`). A `Workspace Sidebar` is auto-generated from a workspace's shortcuts on `migrate` with `standard: 0, app: null` (DB-only). To version it in this app, set `app: "truck_service_center"` and `standard: 1` and save — with `developer_mode` on, `before_save` exports it to `workspace_sidebar/<scrubbed_title>.json`.

3. **`reload-doc` / `migrate` only re-import a record file when its `modified` timestamp is newer than the DB row.** After hand-editing any standard-record JSON (workspace, workspace_sidebar, etc.), bump the `modified` field or the import is silently skipped. Then `clear-cache` and hard-refresh the browser (boot data is cached client-side).

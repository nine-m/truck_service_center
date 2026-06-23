### Truck Service Center

Line Transport Service Center App — a Frappe app for running a truck service-center business: vehicles, service appointments, work orders, repair quotations, and service packages, with stock issue and VAT-aware invoicing.

> **Requires ERPNext** (`required_apps = ["erpnext"]`). The app reuses ERPNext's Item, Warehouse, Customer, Stock Entry, and Sales Invoice.

### Documentation

- [DOCTYPES_README.md](DOCTYPES_README.md) — doctypes, document flow, and business model
- [SETTINGS_README.md](SETTINGS_README.md) — the Truck Service Center Settings singleton
- [CLAUDE.md](CLAUDE.md) — architecture overview + bench/dev commands

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app truck_service_center
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/truck_service_center
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit

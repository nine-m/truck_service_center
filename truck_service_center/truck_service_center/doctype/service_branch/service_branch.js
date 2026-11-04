// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Branch", {
	setup: function (frm) {
		// คลัง/ศูนย์ต้นทุนของสาขาต้องเป็นของบริษัทเดียวกับระบบ — ตรวจซ้ำฝั่ง server
		frappe
			.xcall(
				"truck_service_center.truck_service_center.doctype.truck_service_center_settings.truck_service_center_settings.get_form_defaults"
			)
			.then(function (defaults) {
				let company = defaults && defaults.default_company;
				if (!company) return;
				let by_company = () => ({ filters: { company: company, is_group: 0 } });
				[
					"default_source_warehouse",
					"default_warehouse",
					"default_cost_center",
					"labor_cost_center",
				].forEach((field) => frm.set_query(field, by_company));
			});
	},
});

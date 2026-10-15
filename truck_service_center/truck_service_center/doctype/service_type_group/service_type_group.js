// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Type Group", {
	setup(frm) {
		// Bay Type ใช้ is_active ซึ่ง link search ของ Frappe ไม่กรองให้เอง — ซ่อนประเภทที่ปิดใช้งาน
		frm.set_query("default_bay_type", () => ({ filters: { is_active: 1 } }));
	},
});

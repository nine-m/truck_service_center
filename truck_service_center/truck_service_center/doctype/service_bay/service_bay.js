// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Bay", {
	setup(frm) {
		// Bay Type ใช้ฟิลด์ is_active ซึ่ง link search ของ Frappe ไม่กรองให้เอง
		// (กรองอัตโนมัติเฉพาะ enabled/disabled) ต้องตั้ง query เองไม่งั้นประเภทที่ปิดแล้วยังโผล่
		frm.set_query("bay_type", () => ({ filters: { is_active: 1 } }));
	},
});

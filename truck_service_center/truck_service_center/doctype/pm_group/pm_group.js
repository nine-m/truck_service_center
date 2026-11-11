// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("PM Group", {
	refresh(frm) {
		if (frm.is_new()) return;
		// ทางลัดไปดูช่องจอดในกลุ่มนี้ — การผูกทำที่ Service Bay (หนึ่งช่องจอดอยู่ได้หนึ่งกลุ่ม)
		frm.add_custom_button(__("ช่องจอดในกลุ่ม"), () => {
			frappe.set_route("List", "Service Bay", { pm_group: frm.doc.name });
		});
	}
});

// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Repair Position', {
	refresh: function(frm) {
		// เพิ่ม indicator แสดงสถานะ
		if (frm.doc.is_active) {
			frm.dashboard.add_indicator(__('Active'), 'green');
		} else {
			frm.dashboard.add_indicator(__('Inactive'), 'red');
		}
	},
	
	position_code: function(frm) {
		// แปลงรหัสเป็นตัวพิมพ์ใหญ่อัตโนมัติ
		if (frm.doc.position_code) {
			frm.set_value('position_code', frm.doc.position_code.toUpperCase());
		}
	}
});

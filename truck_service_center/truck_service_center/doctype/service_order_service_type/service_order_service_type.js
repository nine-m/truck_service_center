// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Order Service Type', {
	service_type_group: function(frm, cdt, cdn) {
		// เมื่อเลือกกลุ่มบริการ ให้ล้างค่า service_type
		let row = locals[cdt][cdn];
		
		if (row.service_type) {
			frappe.model.set_value(cdt, cdn, 'service_type', '');
		}
	}
});

// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Appointment Slot', {
	refresh: function(frm) {
		// แสดงจำนวนนัดหมายที่ใช้ slot นี้
		if (!frm.is_new()) {
			frappe.call({
				method: 'frappe.client.get_count',
				args: {
					doctype: 'Service Appointment',
					filters: {
						appointment_slot: frm.doc.name,
						status: ['not in', ['Cancelled', 'No Show']],
						docstatus: ['!=', 2]
					}
				},
				callback: function(r) {
					if (r.message) {
						frm.dashboard.add_indicator(__('Active Appointments: {0}', [r.message]), 'blue');
					}
				}
			});
		}
	}
});

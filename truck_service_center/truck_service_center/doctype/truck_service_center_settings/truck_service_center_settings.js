// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Truck Service Center Settings', {
	refresh: function(frm) {
		// แสดงข้อความช่วยเหลือ
		frm.set_intro(__('Configure default settings for Truck Service Center'));
		
		// แสดงคำเตือนถ้ายังไม่ได้ตั้งค่า Labor Item
		if (!frm.doc.labor_item) {
			frm.dashboard.set_headline_alert(
				__('Please configure Labor Item to enable Sales Invoice creation with labor charges'),
				'orange'
			);
		}
		
		// ปุ่มสร้าง Labor Item อัตโนมัติ
		if (!frm.doc.labor_item) {
			frm.add_custom_button(__('Create Labor Item'), function() {
				frappe.call({
					method: 'truck_service_center.truck_service_center.doctype.truck_service_center_settings.truck_service_center_settings.create_labor_item',
					callback: function(r) {
						if (r.message) {
							frm.set_value('labor_item', r.message);
							frappe.show_alert({
								message: __('Labor Item created successfully'),
								indicator: 'green'
							});
						}
					}
				});
			});
		}
	}
});

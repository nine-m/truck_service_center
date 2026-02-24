// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Vehicle', {
	customer: function(frm) {
		if (frm.doc.customer) {
			frappe.call({
				method: 'truck_service_center.truck_service_center.doctype.vehicle.vehicle.get_customer_contact_info',
				args: { customer: frm.doc.customer },
				callback: function(r) {
					if (r.message) {
						if (r.message.contact_person) {
							frm.set_value('contact_person', r.message.contact_person);
						}
						if (r.message.contact_number) {
							frm.set_value('contact_number', r.message.contact_number);
						}
						if (r.message.email) {
							frm.set_value('email', r.message.email);
						}
					}
				}
			});
		} else {
			frm.set_value('contact_person', '');
			frm.set_value('contact_number', '');
			frm.set_value('email', '');
		}
	},

	refresh: function(frm) {
		// ปุ่มสร้าง Service Order
		if (!frm.is_new()) {
			frm.add_custom_button(__('Create Service Order'), function() {
				frappe.new_doc('Service Order', {
					vehicle: frm.doc.name,
					customer: frm.doc.customer,
					current_mileage: frm.doc.current_mileage
				});
			});
			
			// ปุ่มดูประวัติการบริการ
			frm.add_custom_button(__('Service History'), function() {
				frappe.set_route('List', 'Service Order', {
					vehicle: frm.doc.name
				});
			});
		}
		
		// แสดงการแจ้งเตือนเมื่อเป็นเอกสารที่บันทึกแล้วเท่านั้น
		if (!frm.is_new()) {
			check_service_due(frm);
			check_document_expiry(frm);
		}
	},
	
	current_mileage: function(frm) {
		// ตรวจสอบว่าถึงเวลาบริการหรือยัง
		if (frm.doc.next_service_mileage && frm.doc.current_mileage >= frm.doc.next_service_mileage) {
			frappe.show_alert({
				message: __('Vehicle is due for service!'),
				indicator: 'orange'
			});
		}
	}
});

function check_service_due(frm) {
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.vehicle.vehicle.check_service_due',
		args: {
			vehicle: frm.doc.name
		},
		callback: function(r) {
			if (r.message) {
				frm.dashboard.add_indicator(__('Service Due'), 'orange');
			}
		}
	});
}

function check_document_expiry(frm) {
	let today = frappe.datetime.get_today();
	let warnings = [];
	
	// ตรวจสอบเอกสารที่ใกล้หมดอายุ
	if (frm.doc.insurance_expiry) {
		let days = frappe.datetime.get_day_diff(frm.doc.insurance_expiry, today);
		if (days <= 30 && days >= 0) {
			warnings.push(__('Insurance expires in {0} days', [days]));
		}
	}
	
	if (frm.doc.registration_expiry) {
		let days = frappe.datetime.get_day_diff(frm.doc.registration_expiry, today);
		if (days <= 30 && days >= 0) {
			warnings.push(__('Registration expires in {0} days', [days]));
		}
	}
	
	if (frm.doc.road_tax_expiry) {
		let days = frappe.datetime.get_day_diff(frm.doc.road_tax_expiry, today);
		if (days <= 30 && days >= 0) {
			warnings.push(__('Road Tax expires in {0} days', [days]));
		}
	}
	
	if (frm.doc.inspection_expiry) {
		let days = frappe.datetime.get_day_diff(frm.doc.inspection_expiry, today);
		if (days <= 30 && days >= 0) {
			warnings.push(__('Inspection expires in {0} days', [days]));
		}
	}
	
	// แสดงการแจ้งเตือน
	warnings.forEach(function(warning) {
		frm.dashboard.add_indicator(warning, 'red');
	});
}

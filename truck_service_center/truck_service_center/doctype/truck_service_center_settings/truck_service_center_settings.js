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

		// ตั้งค่า filter สำหรับเทมเพลตภาษีตาม company
		setup_tax_template_filters(frm);

		// แสดงรายละเอียดเทมเพลตที่เลือก
		show_template_details(frm, 'vat_exclusive_template');
		show_template_details(frm, 'vat_inclusive_template');
	},

	default_company: function(frm) {
		// เมื่อเปลี่ยน company ให้ reset filter ของ template
		setup_tax_template_filters(frm);
	},

	vat_exclusive_template: function(frm) {
		show_template_details(frm, 'vat_exclusive_template');
	},

	vat_inclusive_template: function(frm) {
		show_template_details(frm, 'vat_inclusive_template');
	}
});

function setup_tax_template_filters(frm) {
	let company = frm.doc.default_company;
	let filter = company ? { company: company, disabled: 0 } : { disabled: 0 };

	frm.set_query('vat_exclusive_template', function() {
		return { filters: filter };
	});

	frm.set_query('vat_inclusive_template', function() {
		return { filters: filter };
	});
}

function show_template_details(frm, fieldname) {
	let template_name = frm.doc[fieldname];
	if (!template_name) return;

	frappe.call({
		method: 'frappe.client.get',
		args: {
			doctype: 'Sales Taxes and Charges Template',
			name: template_name
		},
		callback: function(r) {
			if (r.message && r.message.taxes) {
				let taxes = r.message.taxes;
				let details = taxes.map(function(tax) {
					let inclusive = tax.included_in_print_rate ? '✅ รวมในราคา' : '❌ ไม่รวมในราคา';
					return `${tax.description || tax.account_head}: ${tax.charge_type} @ ${tax.rate}% (${inclusive})`;
				}).join('<br>');

				frm.fields_dict[fieldname].set_description(details);
			}
		}
	});
}

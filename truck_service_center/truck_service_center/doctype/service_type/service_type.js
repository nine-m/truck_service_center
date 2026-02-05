// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Type', {
	refresh: function(frm) {
		// เพิ่มฟังก์ชันช่วยเหลือ
	},

	item_code: function(frm) {
		// เมื่อเลือก item_code ให้ดึงราคา
		if (frm.doc.item_code) {
			frappe.call({
				method: 'truck_service_center.truck_service_center.doctype.service_type.service_type.get_item_price',
				args: {
					item_code: frm.doc.item_code
				},
				callback: function(r) {
					if (r.message && r.message.price) {
						frm.set_value('labor_rate', r.message.price);
						frappe.msgprint({
							title: __('ราคาดึงมาสำเร็จ'),
							indicator: 'green',
							message: __('ค่าแรง/ค่าบริการ อัปเดตจาก ' + frm.doc.item_code + ' เป็น ' + r.message.price)
						});
					} else {
						frappe.msgprint({
							title: __('ไม่พบราคา'),
							indicator: 'orange',
							message: __('รหัสสินค้า ' + frm.doc.item_code + ' ไม่มีราคาในระบบ กรุณากำหนดราคาเอง')
						});
					}
				}
			});
		}
	}
});

frappe.ui.form.on('Service Type Item', {
	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.item_code) {
			// รอให้ fetch_from ดึงข้อมูลเสร็จก่อน
			setTimeout(() => {
				calculate_item_amount(frm, cdt, cdn);
			}, 500);
		}
	},
	
	qty: function(frm, cdt, cdn) {
		calculate_item_amount(frm, cdt, cdn);
	},
	
	rate: function(frm, cdt, cdn) {
		calculate_item_amount(frm, cdt, cdn);
	},
	
	items_remove: function(frm) {
		frm.refresh_field('items');
	}
});

function calculate_item_amount(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let qty = row.qty || 0;
	let rate = row.rate || 0;
	frappe.model.set_value(cdt, cdn, 'amount', qty * rate);
}

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

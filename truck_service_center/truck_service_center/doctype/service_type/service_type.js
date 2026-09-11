// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Type', {
	refresh: function(frm) {
		// เพิ่มฟังก์ชันช่วยเหลือ
	},

	service_type_group: function(frm) {
		// เปลี่ยนกลุ่มคือการกระทำที่ตั้งใจ จึงทับ bay_type เดิมได้ (ต่างจากฝั่ง server
		// ที่เติมให้เฉพาะตอนว่าง) กลุ่มที่ไม่ได้ตั้งค่าเริ่มต้นไว้ → ไม่แตะค่าเดิม ไม่ล้างทิ้ง
		if (!frm.doc.service_type_group) return;

		frappe.db.get_value('Service Type Group', frm.doc.service_type_group, 'default_bay_type')
			.then(function(r) {
				let bay_type = r.message && r.message.default_bay_type;
				if (bay_type) frm.set_value('bay_type', bay_type);
			});
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
			frappe.call({
				method: 'truck_service_center.truck_service_center.doctype.service_type.service_type.get_item_price',
				args: { item_code: row.item_code },
				callback: function(r) {
					if (r.message && r.message.price) {
						frappe.model.set_value(cdt, cdn, 'rate', r.message.price);
					}
					calculate_item_amount(frm, cdt, cdn);
				}
			});
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

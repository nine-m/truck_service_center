// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Package Item', {
	item_code: function(frm, cdt, cdn) {
		// เมื่อเลือก item ให้ดึงราคาจาก standard price list
		let row = locals[cdt][cdn];
		
		if (row.item_code) {
			frappe.call({
				method: 'frappe.client.get_value',
				args: {
					doctype: 'Item Price',
					filters: {
						item_code: row.item_code,
						price_list: 'Standard Selling'
					},
					fieldname: 'price_list_rate'
				},
				callback: function(r) {
					if (r.message && r.message.price_list_rate) {
						frappe.model.set_value(cdt, cdn, 'rate', r.message.price_list_rate);
					} else {
						// ถ้าไม่มีใน price list ลองดึงจาก item master
						frappe.call({
							method: 'frappe.client.get_value',
							args: {
								doctype: 'Item',
								filters: {
									name: row.item_code
								},
								fieldname: ['standard_rate', 'item_name', 'description']
							},
							callback: function(item_r) {
								if (item_r.message) {
									if (item_r.message.standard_rate) {
										frappe.model.set_value(cdt, cdn, 'rate', item_r.message.standard_rate);
									}
									// อัพเดทคำอธิบายถ้ามี
									if (item_r.message.description && !row.description) {
										frappe.model.set_value(cdt, cdn, 'description', item_r.message.description);
									}
								}
							}
						});
					}
				}
			});
		}
	},

	qty: function(frm, cdt, cdn) {
		// คำนวณยอดรวมเมื่อเปลี่ยนจำนวน
		calculate_amount(frm, cdt, cdn);
	},

	rate: function(frm, cdt, cdn) {
		// คำนวณยอดรวมเมื่อเปลี่ยนราคา
		calculate_amount(frm, cdt, cdn);
	}
});

function calculate_amount(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let amount = (row.qty || 0) * (row.rate || 0);
	frappe.model.set_value(cdt, cdn, 'amount', amount);
}

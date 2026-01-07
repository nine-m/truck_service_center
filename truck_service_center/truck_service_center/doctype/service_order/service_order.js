// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Order', {
	refresh: function(frm) {
		// ปุ่มสร้าง Sales Invoice
		if (frm.doc.docstatus === 1 && !frm.doc.sales_invoice) {
			frm.add_custom_button(__('Create Sales Invoice'), function() {
				frappe.call({
					method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.create_sales_invoice',
					args: {
						service_order: frm.doc.name
					},
					callback: function(r) {
						if (r.message) {
							frappe.msgprint(__('Sales Invoice {0} created', [r.message]));
							frm.reload_doc();
						}
					}
				});
			});
		}
		
		// แสดงสถานะด้วยสี
		if (frm.doc.status === 'Completed') {
			frm.dashboard.add_indicator(__('Status: Completed'), 'green');
		} else if (frm.doc.status === 'In Progress') {
			frm.dashboard.add_indicator(__('Status: In Progress'), 'orange');
		} else if (frm.doc.status === 'On Hold') {
			frm.dashboard.add_indicator(__('Status: On Hold'), 'red');
		}
	},
	
	vehicle: function(frm) {
		// ดึงข้อมูลลูกค้าจากรถ
		if (frm.doc.vehicle) {
			frappe.db.get_value('Vehicle', frm.doc.vehicle, 'customer', function(r) {
				if (r && r.customer) {
					frm.set_value('customer', r.customer);
				}
			});
		}
	},
	
	service_type: function(frm) {
		// ดึงข้อมูลจาก Service Type
		if (frm.doc.service_type) {
			frappe.db.get_value('Service Type', frm.doc.service_type, 
				['default_duration', 'labor_rate', 'item_code'], 
				function(r) {
					if (r) {
						if (r.default_duration) {
							frm.set_value('estimated_time', r.default_duration);
						}
						if (r.labor_rate) {
							frm.set_value('labor_charges', r.labor_rate);
						}
					}
				}
			);
		}
	},
	
	labor_charges: function(frm) {
		calculate_totals(frm);
	},
	
	discount_amount: function(frm) {
		calculate_totals(frm);
	},
	
	tax_amount: function(frm) {
		calculate_totals(frm);
	},
	
	paid_amount: function(frm) {
		calculate_totals(frm);
	}
});

frappe.ui.form.on('Service Order Item', {
	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.item_code) {
			// ดึงข้อมูล Item
			frappe.db.get_value('Item', row.item_code, 
				['item_name', 'description', 'stock_uom', 'standard_rate'], 
				function(r) {
					if (r) {
						frappe.model.set_value(cdt, cdn, 'item_name', r.item_name);
						frappe.model.set_value(cdt, cdn, 'description', r.description);
						frappe.model.set_value(cdt, cdn, 'uom', r.stock_uom);
						frappe.model.set_value(cdt, cdn, 'rate', r.standard_rate);
					}
				}
			);
		}
	},
	
	qty: function(frm, cdt, cdn) {
		calculate_item_amount(frm, cdt, cdn);
	},
	
	rate: function(frm, cdt, cdn) {
		calculate_item_amount(frm, cdt, cdn);
	},
	
	service_items_remove: function(frm) {
		calculate_totals(frm);
	}
});

function calculate_item_amount(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let amount = flt(row.qty) * flt(row.rate);
	frappe.model.set_value(cdt, cdn, 'amount', amount);
	calculate_totals(frm);
}

function calculate_totals(frm) {
	let total_parts = 0;
	
	// คำนวณรวมอะไหล่
	if (frm.doc.service_items) {
		frm.doc.service_items.forEach(function(item) {
			total_parts += flt(item.amount);
		});
	}
	
	frm.set_value('total_parts_amount', total_parts);
	
	// คำนวณยอดรวมสุทธิ
	let subtotal = flt(total_parts) + flt(frm.doc.labor_charges);
	let total = subtotal - flt(frm.doc.discount_amount) + flt(frm.doc.tax_amount);
	frm.set_value('total_amount', total);
	
	// คำนวณยอดคงค้าง
	let outstanding = flt(total) - flt(frm.doc.paid_amount);
	frm.set_value('outstanding_amount', outstanding);
}

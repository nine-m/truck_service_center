// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Order', {
	refresh: function(frm) {
		// ปุ่มสร้าง Sales Invoice
		if (frm.doc.docstatus === 1 && !frm.doc.sales_invoice) {
			frm.add_custom_button(__('Create Sales Invoice'), function() {
				frappe.call({
					method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.create_sales_invoice_from_service_order',
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
		
		// ตั้งค่า filter สำหรับ vehicle ตาม customer
		set_vehicle_filter(frm);
	},
	
	customer: function(frm) {
		// เมื่อเลือก customer ให้ filter รถของลูกค้านั้น
		set_vehicle_filter(frm);
		
		// ล้างค่ารถถ้าเปลี่ยนลูกค้าและรถที่เลือกไว้ไม่ใช่ของลูกค้านี้
		if (frm.doc.vehicle) {
			frappe.db.get_value('Vehicle', frm.doc.vehicle, 'customer', function(r) {
				if (r && r.customer !== frm.doc.customer) {
					frm.set_value('vehicle', '');
				}
			});
		}
	},
	
	vehicle: function(frm) {
		// ดึงข้อมูลลูกค้าจากรถ (ถ้าเลือกรถก่อน)
		if (frm.doc.vehicle) {
			frappe.db.get_value('Vehicle', frm.doc.vehicle, ['customer', 'current_mileage'], function(r) {
				if (r) {
					// ถ้ายังไม่ได้เลือกลูกค้า หรือลูกค้าไม่ตรง ให้เซ็ตลูกค้าใหม่
					if (!frm.doc.customer || frm.doc.customer !== r.customer) {
						frm.set_value('customer', r.customer);
					}
					// ดึงเลขไมล์ปัจจุบัน
					if (r.current_mileage && !frm.doc.current_mileage) {
						frm.set_value('current_mileage', r.current_mileage);
					}
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
	
	service_package: function(frm) {
		if (frm.doc.service_package) {
			frappe.call({
				method: "truck_service_center.truck_service_center.doctype.service_package.service_package.get_package_details",
				args: {
					package_name: frm.doc.service_package
				},
				callback: function(r) {
					if (r.message) {
						// Clear existing items
						frm.clear_table("service_items");
						
						// Add package items
						r.message.items.forEach(function(item) {
							let row = frm.add_child("service_items");
							row.item_code = item.item_code;
							row.item_name = item.item_name;
							row.qty = item.qty;
							row.rate = item.rate;
							row.amount = item.amount;
							row.description = item.description;
						});
						
						// Set discount
						if (r.message.discount_amount) {
							frm.set_value("discount_amount", r.message.discount_amount);
						}
						
						// Refresh items table
						frm.refresh_field("service_items");
						frm.refresh_field("discount_amount");
						
						frappe.show_alert({
							message: __("Package items loaded successfully"),
							indicator: "green"
						});
					}
				}
			});
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
			// ดึงข้อมูล Item และราคาจาก Item Price
			frappe.call({
				method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_item_rate',
				args: {
					item_code: row.item_code,
					customer: frm.doc.customer
				},
				callback: function(r) {
					if (r.message) {
						frappe.model.set_value(cdt, cdn, 'item_name', r.message.item_name);
						frappe.model.set_value(cdt, cdn, 'description', r.message.description);
						frappe.model.set_value(cdt, cdn, 'uom', r.message.uom);
						frappe.model.set_value(cdt, cdn, 'rate', r.message.rate || 0);
						
						// แสดงข้อความถ้าราคาเป็น 0
						if (!r.message.rate || r.message.rate === 0) {
							frappe.show_alert({
								message: __('No price found for this item. Please set Item Price or Standard Rate.'),
								indicator: 'orange'
							});
						}
					}
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

function set_vehicle_filter(frm) {
	// ตั้งค่า filter สำหรับ Vehicle ให้แสดงเฉพาะรถของลูกค้าที่เลือก
	if (frm.doc.customer) {
		frm.set_query('vehicle', function() {
			return {
				filters: {
					'customer': frm.doc.customer,
					'status': 'Active'
				}
			};
		});
	} else {
		// ถ้ายังไม่ได้เลือกลูกค้า ให้แสดงเฉพาะรถที่ Active
		frm.set_query('vehicle', function() {
			return {
				filters: {
					'status': 'Active'
				}
			};
		});
	}
}

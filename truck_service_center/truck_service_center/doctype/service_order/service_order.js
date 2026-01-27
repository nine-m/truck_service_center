// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Order', {
	onload: function(frm) {
		// คำนวณยอดรวมเมื่อโหลดครั้งแรก
		calculate_totals(frm);
	},
	
	refresh: function(frm) {
		// ตั้งค่า filter สำหรับ service_type ใน child table
		setup_service_type_filter(frm);
		
		// แสดงสรุป Material Issues
		show_material_issue_summary(frm);
		
		// ปุ่มสร้าง Material Issue (สำหรับ items ที่ยังไม่มีใบเบิก)
		if (frm.doc.docstatus === 0 && frm.doc.service_items && frm.doc.service_items.length > 0) {
			// ตรวจสอบว่ามี item ที่ยังไม่มี Material Issue หรือไม่
			let has_unlinked_items = frm.doc.service_items.some(item => !item.material_issue && item.item_code);
			
			if (has_unlinked_items) {
				frm.add_custom_button(__('Create Material Issue'), function() {
					create_material_issue_dialog(frm);
				}, __('Actions'));
			}
		}
		
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
		// ดึงข้อมูลลูกค้าและข้อมูลติดต่อจากรถ
		if (frm.doc.vehicle) {
			frappe.db.get_value('Vehicle', frm.doc.vehicle, 
				['customer', 'current_mileage', 'contact_person', 'contact_number', 'email'], 
				function(r) {
					if (r) {
						// ถ้ายังไม่ได้เลือกลูกค้า หรือลูกค้าไม่ตรง ให้เซ็ตลูกค้าใหม่
						if (!frm.doc.customer || frm.doc.customer !== r.customer) {
							frm.set_value('customer', r.customer);
						}
						// ดึงเลขไมล์ปัจจุบัน (ดึงทุกครั้งเพื่ออัพเดทเป็นค่าล่าสุด)
						if (r.current_mileage) {
							frm.set_value('current_mileage', r.current_mileage);
						}
						// ดึงข้อมูลติดต่อ (ถ้ายังไม่ได้กรอก)
						if (r.contact_person && !frm.doc.contact_person) {
							frm.set_value('contact_person', r.contact_person);
						}
						if (r.contact_number && !frm.doc.contact_number) {
							frm.set_value('contact_number', r.contact_number);
						}
						if (r.email && !frm.doc.email) {
							frm.set_value('email', r.email);
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

// Event handlers สำหรับ child table ประเภทบริการ
frappe.ui.form.on('Service Order Service Type', {
	service_types_add: function(frm) {
		calculate_totals(frm);
	},
	
	service_types_remove: function(frm) {
		calculate_totals(frm);
	},
	
	labor_charges: function(frm, cdt, cdn) {
		calculate_totals(frm);
	},
	
	estimated_time: function(frm, cdt, cdn) {
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
		calculate_totals(frm);
	},
	
	rate: function(frm, cdt, cdn) {
		calculate_item_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},
	
	service_items_add: function(frm) {
		calculate_totals(frm);
	},
	
	service_items_remove: function(frm) {
		calculate_totals(frm);
	},
	
	material_issue: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		
		// ถ้ามี Material Issue ให้ทำให้ field อื่นเป็น read-only
		if (row.material_issue) {
			// ดึงสถานะของ Material Issue
			frappe.db.get_value('Stock Entry', row.material_issue, 'docstatus', function(r) {
				if (r && r.docstatus !== undefined) {
					let status_map = {0: 'Draft', 1: 'Submitted', 2: 'Cancelled'};
					frappe.model.set_value(cdt, cdn, 'material_issue_status', status_map[r.docstatus]);
					
					// ถ้า Material Issue เป็น Submitted แล้ว ไม่ให้แก้ไข item นี้
					if (r.docstatus === 1) {
						frm.fields_dict.service_items.grid.update_docfield_property('item_code', 'read_only', 1, cdn);
						frm.fields_dict.service_items.grid.update_docfield_property('qty', 'read_only', 1, cdn);
						frm.fields_dict.service_items.grid.update_docfield_property('rate', 'read_only', 1, cdn);
						frm.fields_dict.service_items.grid.update_docfield_property('warehouse', 'read_only', 1, cdn);
					}
				}
			});
		}
	}
});

function calculate_item_amount(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let amount = flt(row.qty) * flt(row.rate);
	frappe.model.set_value(cdt, cdn, 'amount', amount);
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

// คำนวณยอดรวมทั้งหมด
function calculate_totals(frm) {
	// คำนวณค่าแรงรวมและเวลาประมาณการรวม
	let total_labor = 0;
	let total_time = 0;
	
	if (frm.doc.service_types) {
		frm.doc.service_types.forEach(function(row) {
			total_labor += flt(row.labor_charges);
			total_time += flt(row.estimated_time);
		});
	}
	
	// อัพเดทค่าแรงและเวลารวม
	frm.set_value('labor_charges', total_labor);
	frm.set_value('estimated_time', total_time);
	
	// คำนวณยอดรวมอะไหล่
	let total_parts = 0;
	if (frm.doc.service_items) {
		frm.doc.service_items.forEach(function(item) {
			total_parts += flt(item.qty) * flt(item.rate);
		});
	}
	frm.set_value('total_parts_amount', total_parts);
	
	// คำนวณยอดรวมทั้งหมด
	let subtotal = total_parts + total_labor;
	let total = subtotal - flt(frm.doc.discount_amount) + flt(frm.doc.tax_amount);
	frm.set_value('total_amount', total);
	
	// คำนวณยอดคงค้าง
	let outstanding = total - flt(frm.doc.paid_amount);
	frm.set_value('outstanding_amount', outstanding);
}

function setup_service_type_filter(frm) {
	// ตั้งค่า filter สำหรับ service_type ใน child table service_types
	frm.set_query('service_type', 'service_types', function(doc, cdt, cdn) {
		let row = locals[cdt][cdn];
		let filters = {
			'is_active': 1
		};
		
		// ถ้ามีการเลือก service_type_group ให้ filter ตาม group
		if (row.service_type_group) {
			filters['service_type_group'] = row.service_type_group;
		}
		
		return {
			filters: filters
		};
	});
}

function show_material_issue_summary(frm) {
	if (!frm.doc.name || frm.doc.__islocal) return;
	
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_material_issue_summary',
		args: {
			service_order: frm.doc.name
		},
		callback: function(r) {
			if (r.message) {
				let summary = r.message;
				let html = '';
				
				if (summary.total_count > 0) {
					html = '<div class="row">';
					html += '<div class="col-12"><h5>Material Issues (' + summary.total_count + ')</h5></div>';
					
					summary.material_issues.forEach(function(issue) {
						let badge_class = issue.status === 'Submitted' ? 'success' : 
										  issue.status === 'Draft' ? 'warning' : 'danger';
						
						html += '<div class="col-md-6 col-12" style="margin-bottom: 10px;">';
						html += '<div class="card" style="border-left: 3px solid var(--bs-' + badge_class + ');">';
						html += '<div class="card-body" style="padding: 10px;">';
						html += '<a href="/app/stock-entry/' + issue.name + '" target="_blank"><strong>' + issue.name + '</strong></a>';
						html += '<span class="badge badge-' + badge_class + '" style="float: right;">' + issue.status + '</span>';
						html += '<br><small>' + issue.posting_date + ' | Items: ' + issue.item_count + '</small>';
						
						// ปุ่ม Sync สำหรับ Draft
						if (issue.status === 'Draft') {
							html += '<br><button class="btn btn-xs btn-default" style="margin-top: 5px;" ';
							html += 'onclick="sync_material_issue(\'' + frm.doc.name + '\', \'' + issue.name + '\')">';
							html += '<i class="fa fa-refresh"></i> Sync</button>';
						}
						
						html += '</div></div></div>';
					});
					
					html += '</div>';
				} else {
					html = '<p class="text-muted">ยังไม่มี Material Issue</p>';
				}
				
				frm.fields_dict.material_issue_summary.$wrapper.html(html);
			}
		}
	});
}

function create_material_issue_dialog(frm) {
	// แสดง dialog เพื่อให้เลือก items ที่จะสร้าง Material Issue
	let unlinked_items = [];
	
	frm.doc.service_items.forEach(function(item, idx) {
		if (!item.material_issue && item.item_code) {
			unlinked_items.push({
				idx: idx,
				item_code: item.item_code,
				item_name: item.item_name,
				qty: item.qty,
				warehouse: item.warehouse
			});
		}
	});
	
	if (unlinked_items.length === 0) {
		frappe.msgprint(__('All items are already linked to Material Issues'));
		return;
	}
	
	// สร้าง Material Issue สำหรับทุก item ที่ยังไม่ link
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.create_material_issue',
		args: {
			service_order: frm.doc.name
		},
		callback: function(r) {
			if (r.message) {
				frappe.show_alert({
					message: __('Material Issue {0} created', [r.message]),
					indicator: 'green'
				});
				frm.reload_doc();
			}
		}
	});
}

window.sync_material_issue = function(service_order, material_issue) {
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.sync_material_issue',
		args: {
			service_order: service_order,
			material_issue: material_issue
		},
		callback: function(r) {
			if (r.message) {
				cur_frm.reload_doc();
			}
		}
	});
};

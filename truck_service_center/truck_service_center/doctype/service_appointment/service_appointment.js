// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Appointment', {
	refresh: function(frm) {
		// ให้ยอดขยับตั้งแต่ตอนพิมพ์ ไม่ต้องรอออกจากช่อง
		setup_live_row_calc(frm);

		// ปุ่มสร้าง Service Order
		if (frm.doc.docstatus === 1 && !frm.doc.service_order && frm.doc.status !== 'Cancelled') {
			frm.add_custom_button(__('Create Service Order'), function() {
				frappe.call({
					method: 'truck_service_center.truck_service_center.doctype.service_appointment.service_appointment.create_service_order_from_appointment',
					args: {
						appointment: frm.doc.name
					},
					callback: function(r) {
						if (r.message) {
							frappe.msgprint(__('Service Order {0} created', [r.message]));
							frm.reload_doc();
						}
					}
				});
			}).addClass('btn-primary');
		}
		
		// ปุ่ม Mark as Completed
		if (frm.doc.docstatus === 1 && frm.doc.status === 'In Progress') {
			frm.add_custom_button(__('Mark as Completed'), function() {
				frappe.call({
					method: 'frappe.client.set_value',
					args: {
						doctype: 'Service Appointment',
						name: frm.doc.name,
						fieldname: 'status',
						value: 'Completed'
					},
					callback: function() {
						frm.reload_doc();
					}
				});
			});
		}
		
		// ปุ่ม Mark as No Show
		if (frm.doc.docstatus === 1 && frm.doc.status === 'Confirmed') {
			frm.add_custom_button(__('Mark as No Show'), function() {
				frappe.confirm(
					__('Are you sure the customer did not show up?'),
					function() {
						frappe.call({
							method: 'frappe.client.set_value',
							args: {
								doctype: 'Service Appointment',
								name: frm.doc.name,
								fieldname: 'status',
								value: 'No Show'
							},
							callback: function() {
								frm.reload_doc();
							}
						});
					}
				);
			});
		}
		
		// แสดงสถานะด้วยสี
		if (frm.doc.status === 'Confirmed') {
			frm.dashboard.add_indicator(__('Status: Confirmed'), 'blue');
		} else if (frm.doc.status === 'In Progress') {
			frm.dashboard.add_indicator(__('Status: In Progress'), 'orange');
		} else if (frm.doc.status === 'Completed') {
			frm.dashboard.add_indicator(__('Status: Completed'), 'green');
		} else if (frm.doc.status === 'Cancelled') {
			frm.dashboard.add_indicator(__('Status: Cancelled'), 'red');
		}
		
		// ตั้งค่า filter สำหรับ vehicle
		set_vehicle_filter(frm);
		
		// ตั้งค่า filter สำหรับ address ตาม customer
		set_address_filters(frm);
		
		// ตั้งค่า filter สำหรับ service_package ในตาราง packages
		setup_service_package_filter(frm);

		// ตั้งค่า filter สำหรับช่างที่มอบหมาย
		set_technician_filter(frm);
	},

	customer: function(frm) {
		// ตั้งค่า filter สำหรับ vehicle
		set_vehicle_filter(frm);
		
		// ตั้งค่า filter สำหรับ address ตาม customer
		set_address_filters(frm);
		
		// ดึง default billing/shipping address ของลูกค้า
		if (frm.doc.customer) {
			fetch_customer_addresses(frm);
		} else {
			// ล้างค่า address ถ้าไม่มีลูกค้า
			frm.set_value('customer_address', '');
			frm.set_value('address_display', '');
			frm.set_value('shipping_address_name', '');
			frm.set_value('shipping_address', '');
		}
		
		// ล้างค่ารถถ้าเปลี่ยนลูกค้า
		if (frm.doc.vehicle) {
			frappe.db.get_value('Vehicle', frm.doc.vehicle, 'customer', function(r) {
				if (r && r.customer !== frm.doc.customer) {
					frm.set_value('vehicle', '');
				}
			});
		}
	},
	
	customer_address: function(frm) {
		// เมื่อเลือก billing address ให้ render address display
		if (frm.doc.customer_address) {
			frappe.call({
				method: 'frappe.contacts.doctype.address.address.get_address_display',
				args: { address_dict: frm.doc.customer_address },
				callback: function(r) {
					if (r.message) {
						frm.set_value('address_display', r.message);
					}
				}
			});
		} else {
			frm.set_value('address_display', '');
		}
	},
	
	shipping_address_name: function(frm) {
		// เมื่อเลือก shipping address ให้ render address display
		if (frm.doc.shipping_address_name) {
			frappe.call({
				method: 'frappe.contacts.doctype.address.address.get_address_display',
				args: { address_dict: frm.doc.shipping_address_name },
				callback: function(r) {
					if (r.message) {
						frm.set_value('shipping_address', r.message);
					}
				}
			});
		} else {
			frm.set_value('shipping_address', '');
		}
	},
	
	vehicle: function(frm) {
		// ดึงข้อมูลลูกค้าจากรถ
		if (frm.doc.vehicle) {
			frappe.db.get_value('Vehicle', frm.doc.vehicle, ['customer', 'license_plate'], function(r) {
				if (r) {
					if (r.customer && (!frm.doc.customer || frm.doc.customer !== r.customer)) {
						frm.set_value('customer', r.customer);
					}
					if (r.license_plate && frm.get_field('license_plate')) {
						frm.set_value('license_plate', r.license_plate);
					}
				}
			});
		}
	},
	
	appointment_date: function(frm) {
		// แสดงช่วงเวลาว่างพร้อม available seats
		if (frm.doc.appointment_date) {
			show_available_slots(frm);
		}
		
		// ตั้ง filter slot ที่ยังมีที่ว่าง
		set_slot_filter(frm);
	},
	
	appointment_slot: function(frm) {
		// แสดง capacity ของ slot ที่เลือก
		if (frm.doc.appointment_slot && frm.doc.appointment_date) {
			show_slot_info(frm);
		}
	},
	
	assigned_technician: function(frm) {
		// ไม่ต้องทำอะไร - ระบบใหม้ไม่ check ช่างอีกต่อไป
	}
});

function set_technician_filter(frm) {
	// แสดงเฉพาะผู้ใช้ที่มีบทบาท Technician
	frm.set_query('assigned_technician', function() {
		return {
			query: 'truck_service_center.queries.technician_query'
		};
	});
}

function set_vehicle_filter(frm) {
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
		frm.set_query('vehicle', function() {
			return {
				filters: {
					'status': 'Active'
				}
			};
		});
	}
}

function show_available_slots(frm) {
	if (!frm.doc.appointment_date) return;
	
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_appointment.service_appointment.get_available_slots',
		args: {
			date: frm.doc.appointment_date
		},
		callback: function(r) {
			if (r.message && r.message.length > 0) {
				// สร้าง HTML table แสดง slots (คลิกแถวเพื่อเลือกช่วงเวลา)
				let html = '<p class="text-muted" style="margin-bottom: 5px;">คลิกช่วงเวลาที่ต้องการเพื่อเลือก</p>';
				html += '<table class="table table-bordered" style="margin-top: 5px;">';
				html += '<thead><tr><th>ช่วงเวลา</th><th>เวลา</th><th>ว่าง/ทั้งหมด</th></tr></thead>';
				html += '<tbody>';

				r.message.forEach(function(slot) {
					let badge_class = slot.available > 0 ? 'badge-success' : 'badge-danger';
					html += `<tr class="slot-row" data-slot="${frappe.utils.escape_html(slot.slot)}" style="cursor: pointer;">`;
					html += `<td><strong>${slot.slot_name}</strong></td>`;
					html += `<td>${slot.start_time} - ${slot.end_time}</td>`;
					html += `<td><span class="badge ${badge_class}">${slot.available}/${slot.capacity}</span></td>`;
					html += '</tr>';
				});

				html += '</tbody></table>';

				// แสดงผลใน dialog
				let d = new frappe.ui.Dialog({
					title: __('Available Time Slots - {0}', [frm.doc.appointment_date]),
					fields: [
						{
							fieldtype: 'HTML',
							options: html
						}
					],
					size: 'small'
				});
				d.show();

				// คลิกแถวเพื่อเลือก slot แล้วใส่ลงช่องช่วงเวลาให้อัตโนมัติ
				d.$wrapper.find('.slot-row').on('click', function() {
					let slot_name = $(this).data('slot');
					d.hide();
					frm.set_value('appointment_slot', slot_name);
				}).hover(
					function() { $(this).addClass('active'); },
					function() { $(this).removeClass('active'); }
				);
			} else {
				frappe.msgprint(__('No available slots for this date'));
			}
		}
	});
}

function set_slot_filter(frm) {
	if (frm.doc.appointment_date) {
		frm.set_query('appointment_slot', function() {
			return {
				filters: {
					'is_active': 1
				}
			};
		});
	}
}

function show_slot_info(frm) {
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_appointment_slot.service_appointment_slot.get_slot_availability',
		args: {
			date: frm.doc.appointment_date,
			slot: frm.doc.appointment_slot
		},
		callback: function(r) {
			if (r.message && r.message.length > 0) {
				let slot = r.message[0];
				let message = `${slot.slot_name}: ${slot.start_time}-${slot.end_time} | ว่าง: ${slot.available}/${slot.capacity} คัน`;
				let indicator = slot.available > 0 ? 'green' : 'red';
				
				frappe.show_alert({
					message: message,
					indicator: indicator
				}, 5);
			}
		}
	});
}

// Event handlers สำหรับ child table แพ็คเกจบริการ
frappe.ui.form.on('Service Appointment Package', {
	service_package: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.service_package) return;
		
		frappe.call({
			method: "truck_service_center.truck_service_center.doctype.service_package.service_package.get_package_details",
			args: { package_name: row.service_package },
			callback: function(r) {
				if (!r.message) return;
				let pkg = r.message;
				let pkg_name = row.service_package;
				let discount_pct = flt(pkg.discount_percent);
				
				// เพิ่ม service types จาก package
				(pkg.service_types || []).forEach(function(st) {
					let st_row = frm.add_child('service_types');
					st_row.service_type = st.service_type;
					st_row.service_type_group = st.service_type_group;
					st_row.maintenance_type = st.maintenance_type;
					st_row.estimated_time = st.estimated_time;
					st_row.labor_charges = st.labor_rate;
					st_row.service_package = pkg_name;
				});
				
				// เพิ่ม parts จาก package
				(pkg.parts || []).forEach(function(part) {
					let item_row = frm.add_child('service_items');
					item_row.item_code = part.item_code;
					item_row.item_name = part.item_name;
					item_row.qty = part.qty;
					item_row.uom = part.uom;
					item_row.rate = part.rate;
					item_row.amount = flt(part.qty) * flt(part.rate);
					item_row.service_package = pkg_name;
				});
				
				frm.refresh_field('service_types');
				frm.refresh_field('service_items');
				
				calculate_estimated_duration(frm);
				calculate_totals(frm);
				
				frappe.show_alert({
					message: __('โหลดรายการจากแพ็คเกจ "{0}" เรียบร้อย', [pkg.package_name || pkg_name]),
					indicator: 'green'
				});
			}
		});
	},
	
	service_packages_remove: function(frm) {
		// Cascade delete
		let current_packages = new Set();
		(frm.doc.service_packages || []).forEach(function(pkg_row) {
			if (pkg_row.service_package) {
				current_packages.add(pkg_row.service_package);
			}
		});
		
		frm.doc.service_types = (frm.doc.service_types || []).filter(function(st) {
			return !st.service_package || current_packages.has(st.service_package);
		});
		frm.doc.service_items = (frm.doc.service_items || []).filter(function(si) {
			return !si.service_package || current_packages.has(si.service_package);
		});
		
		frm.doc.service_types.forEach(function(row, idx) { row.idx = idx + 1; });
		frm.doc.service_items.forEach(function(row, idx) { row.idx = idx + 1; });
		
		frm.refresh_field('service_types');
		frm.refresh_field('service_items');
		calculate_estimated_duration(frm);
		calculate_totals(frm);
	}
});

frappe.ui.form.on('Service Appointment Service Type', {
	service_type: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.service_type) return;

		// ดึงรายการอะไหล่มาตรฐานจาก Service Type (เหมือนใบสั่งงาน)
		frappe.call({
			method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_service_type_items',
			args: { service_type: row.service_type },
			callback: function(r) {
				if (!r.message || !r.message.length) return;

				let items = r.message;
				let item_list = items.map(function(item) {
					return `• ${item.item_name || item.item_code} - จำนวน: ${item.qty} ${item.uom || ''} (฿${item.rate || 0})`;
				}).join('<br>');

				frappe.confirm(
					__('ประเภทบริการ "{0}" มีรายการอะไหล่มาตรฐาน {1} รายการ:<br><br>{2}<br><br>ต้องการเพิ่มรายการอะไหล่เหล่านี้ในนัดหมายหรือไม่?',
						[row.service_type, items.length, item_list]),
					function() {
						add_service_type_items(frm, items);

						frappe.show_alert({
							message: __('เพิ่มรายการอะไหล่ {0} รายการจาก "{1}" เรียบร้อย',
								[items.length, row.service_type]),
							indicator: 'green'
						});
					}
				);
			}
		});
	},
	estimated_time: function(frm) {
		calculate_estimated_duration(frm);
	},
	labor_charges: function(frm) {
		calculate_totals(frm);
	},
	service_types_add: function(frm) {
		calculate_estimated_duration(frm);
		calculate_totals(frm);
	},
	service_types_remove: function(frm) {
		calculate_estimated_duration(frm);
		calculate_totals(frm);
	}
});

frappe.ui.form.on('Service Appointment Item', {
	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.item_code) {
			// ใช้ราคาขายชุดเดียวกับใบสั่งงาน (Item Price → standard_rate → ราคาทุน)
			// ไม่ดึง valuation_rate ตรง ๆ เพราะนั่นคือราคาทุน ไม่ใช่ราคาที่จะเก็บลูกค้า
			frappe.call({
				method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_item_rate',
				args: {
					item_code: row.item_code,
					customer: frm.doc.customer
				},
				callback: function(r) {
					if (!r.message) return;

					frappe.model.set_value(cdt, cdn, 'rate', flt(r.message.rate));
					// สรุปยอดทันที ไม่ต้องรอ trigger ของ rate (ถ้าราคาเท่าเดิม trigger จะไม่ยิง)
					calculate_item_amount(frm, cdt, cdn);
					calculate_totals(frm);

					if (!flt(r.message.rate)) {
						frappe.show_alert({
							message: __('ไม่พบราคาสำหรับสินค้านี้ กรุณาตั้งค่า Item Price'),
							indicator: 'orange'
						});
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
	}
});

function add_service_type_items(frm, items) {
	// รวมกับแถวเดิมถ้ามี item_code ซ้ำ มิฉะนั้นสร้างแถวใหม่
	items.forEach(function(item) {
		let existing = (frm.doc.service_items || []).find(function(si) {
			return si.item_code === item.item_code;
		});

		if (existing) {
			existing.qty = flt(existing.qty) + flt(item.qty);
			existing.amount = flt(existing.qty) * flt(existing.rate);
		} else {
			let new_row = frm.add_child('service_items');
			new_row.item_code = item.item_code;
			new_row.item_name = item.item_name;
			new_row.qty = item.qty;
			new_row.uom = item.uom;
			new_row.rate = item.rate;
			new_row.amount = flt(item.amount) || flt(item.qty) * flt(item.rate);
		}
	});

	frm.refresh_field('service_items');
	calculate_totals(frm);
}

function calculate_item_amount(frm, cdt, cdn) {
	// เขียนผ่าน model เพื่อให้ช่อง "ยอดรวม" ในตารางอัปเดตตามทันที
	// (ห้ามแก้ row.amount เองก่อน ไม่งั้น set_value จะเห็นว่าค่าไม่เปลี่ยนแล้วไม่วาดช่องใหม่)
	let row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, 'amount', flt(flt(row.qty) * flt(row.rate), 2));
}

// ปกติ Frappe จะคำนวณให้ตอน "ออกจากช่อง" (event change) เท่านั้น
// สองฟังก์ชันนี้ทำให้ยอดในแถวและยอดรวมท้ายเอกสารขยับตั้งแต่ตอนพิมพ์
function setup_live_row_calc(frm) {
	bind_live_row_calc(frm, 'service_items', ['qty', 'rate'], calculate_item_amount);
	bind_live_row_calc(frm, 'service_types', ['labor_charges', 'estimated_time'], null);
}

function bind_live_row_calc(frm, gridfield, fieldnames, recalc_row) {
	let field = frm.fields_dict[gridfield];
	if (!field || !field.grid || field.grid.__live_row_calc) return;

	let grid = field.grid;
	grid.__live_row_calc = true;

	grid.wrapper.on('input', 'input[data-fieldname]', function() {
		let fieldname = $(this).attr('data-fieldname');
		if (fieldnames.indexOf(fieldname) === -1) return;

		let cdt = grid.doctype;
		let cdn = $(this).closest('.grid-row').attr('data-name');
		let row = cdn && locals[cdt] && locals[cdt][cdn];
		if (!row) return;

		// เขียนค่าที่กำลังพิมพ์ลงแถวตรง ๆ ไม่ผ่าน frappe.model.set_value
		// เพราะ set_value จะ format ค่าในช่องที่กำลังพิมพ์ใหม่ทันที (พิมพ์ทศนิยมต่อไม่ได้)
		// ค่าจริงจะถูกคอมมิตอีกครั้งตอนออกจากช่องตามกลไกปกติของ Frappe
		row[fieldname] = flt($(this).val());
		if (!frm.doc.__unsaved) frm.dirty();
		recalc_row && recalc_row(frm, cdt, cdn);
		calculate_estimated_duration(frm);
		calculate_totals(frm);
	});
}

function calculate_estimated_duration(frm) {
	let total = 0;
	(frm.doc.service_types || []).forEach(function(row) {
		total += flt(row.estimated_time);
	});
	frm.set_value('estimated_duration', total);
}

function calculate_totals(frm) {
	let total_labor = 0;
	let total_parts = 0;
	(frm.doc.service_types || []).forEach(function(row) {
		total_labor += flt(row.labor_charges);
	});
	(frm.doc.service_items || []).forEach(function(row) {
		total_parts += flt(row.amount);
	});
	frm.set_value('total_labor_charges', total_labor);
	frm.set_value('total_parts_amount', total_parts);
	frm.set_value('total_amount', total_labor + total_parts);
}

function setup_service_package_filter(frm) {
	frm.set_query('service_package', 'service_packages', function() {
		return {
			filters: { 'is_active': 1 }
		};
	});
}

// ====== Address Helper Functions ======

function set_address_filters(frm) {
	// Filter billing address ตาม customer (ผ่าน Dynamic Link)
	frm.set_query('customer_address', function() {
		return {
			query: 'frappe.contacts.doctype.address.address.address_query',
			filters: {
				link_doctype: 'Customer',
				link_name: frm.doc.customer || ''
			}
		};
	});
	
	// Filter shipping address ตาม customer (ผ่าน Dynamic Link)
	frm.set_query('shipping_address_name', function() {
		return {
			query: 'frappe.contacts.doctype.address.address.address_query',
			filters: {
				link_doctype: 'Customer',
				link_name: frm.doc.customer || ''
			}
		};
	});
}

function fetch_customer_addresses(frm) {
	// ดึง default billing address ของลูกค้า
	frappe.call({
		method: 'frappe.contacts.doctype.address.address.get_default_address',
		args: {
			doctype: 'Customer',
			name: frm.doc.customer
		},
		callback: function(r) {
			if (r.message) {
				frm.set_value('customer_address', r.message);
			} else {
				frm.set_value('customer_address', '');
				frm.set_value('address_display', '');
			}
		}
	});
	
	// ดึง default shipping address ของลูกค้า
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_appointment.service_appointment.get_party_shipping_address',
		args: {
			doctype: 'Customer',
			name: frm.doc.customer
		},
		callback: function(r) {
			if (r.message) {
				frm.set_value('shipping_address_name', r.message);
			} else {
				frm.set_value('shipping_address_name', '');
				frm.set_value('shipping_address', '');
			}
		}
	});
}

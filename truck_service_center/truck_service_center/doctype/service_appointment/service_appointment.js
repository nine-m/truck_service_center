// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Appointment', {
	refresh: function(frm) {
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
	},
	
	customer: function(frm) {
		// ตั้งค่า filter สำหรับ vehicle
		set_vehicle_filter(frm);
		
		// ล้างค่ารถถ้าเปลี่ยนลูกค้า
		if (frm.doc.vehicle) {
			frappe.db.get_value('Vehicle', frm.doc.vehicle, 'customer', function(r) {
				if (r && r.customer !== frm.doc.customer) {
					frm.set_value('vehicle', '');
				}
			});
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
				// สร้าง HTML table แสดง slots
				let html = '<table class="table table-bordered" style="margin-top: 10px;">';
				html += '<thead><tr><th>ช่วงเวลา</th><th>เวลา</th><th>ว่าง/ทั้งหมด</th></tr></thead>';
				html += '<tbody>';
				
				r.message.forEach(function(slot) {
					let badge_class = slot.available > 0 ? 'badge-success' : 'badge-danger';
					html += '<tr>';
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

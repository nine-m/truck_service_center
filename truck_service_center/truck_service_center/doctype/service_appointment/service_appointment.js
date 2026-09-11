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

		// ตั้งค่า filter สำหรับช่องจอดในตารางช่องจอดที่จัดให้
		set_bay_filter(frm);

		// wrapper ของ HTML field ถูกล้างทุก refresh จึงต้องวาดใหม่ทุกครั้ง
		// (refresh ยิงหลัง save อยู่แล้ว ตัวเลขหลังบันทึกจึงอัปเดตตามไปด้วย)
		load_capacity_meter(frm);

		// ปุ่มให้ระบบจัดช่องจอดใหม่ (ล้างของเดิมทิ้งแล้วจัดใหม่)
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__('จัด Bay ใหม่'), function() {
				reallocate_bays(frm);
			});
		}
	},

	before_save: function(frm) {
		// เตือน + ขอคำยืนยันก่อนบันทึกเมื่อจะใช้เกินความจุของช่องจอด
		// ต้อง reject promise เท่านั้นถึงจะหยุดการบันทึกได้ (return false ไม่มีผล)
		return confirm_capacity_before_save(frm);
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
		// อัปเดตแถบความจุของวันที่เลือก (ชั่วโมงที่จองแล้ว / ที่รับได้)
		load_capacity_meter(frm);
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

function set_bay_filter(frm) {
	frm.set_query('service_bay', 'bay_allocations', function(doc, cdt, cdn) {
		let row = locals[cdt][cdn];
		let filters = { 'is_active': 1 };
		// แถวรู้อยู่แล้วว่าเป็นงานประเภทไหน — กรองให้เหลือเฉพาะช่องจอดประเภทนั้น
		// จะได้เลือกผิดประเภทด้วยมือยากขึ้น (ยังเตือนฝั่ง server อยู่ดีถ้าเลือกผิด)
		if (row && row.bay_type) filters.bay_type = row.bay_type;
		return { filters: filters };
	});
}

function bay_status_badge(status) {
	let classes = {
		'ว่าง': 'badge-success',
		'ใกล้เต็ม': 'badge-warning',
		'เต็ม': 'badge-danger',
		'ปิดทำการ': 'badge-secondary'
	};
	return classes[status] || 'badge-secondary';
}

function fmt_hours(hours) {
	// ตัด .00 ทิ้ง แต่คงทศนิยมที่มีค่าจริงไว้ — "8 ชม." อ่านง่ายกว่า "8.00 ชม."
	const value = flt(hours, 2);
	return String(parseFloat(value.toFixed(2)));
}

function load_capacity_meter(frm) {
	const field = frm.get_field('capacity_html');
	if (!field) return;

	if (!frm.doc.appointment_date) {
		field.$wrapper.empty();
		return;
	}

	// เปลี่ยนวันรัวๆ แล้วคำตอบของวันเก่าอาจกลับมาทีหลัง — นับ request ไว้แล้วทิ้งของเก่า
	frm._capacity_req = (frm._capacity_req || 0) + 1;
	const req = frm._capacity_req;

	// meter เป็นภาพ "ทั้งวัน" ไม่ใช่ "ยังจองได้อีกเท่าไร" จึงต้องไม่ exclude ใบนี้ออก
	// ใบที่บันทึกแล้วถูกตัดออกจากตัวเลข ทำให้ก่อนกับหลังบันทึกได้เลขเท่ากันเป๊ะ ดูเหมือน
	// ไม่อัปเดต และผู้ใช้เห็นชั่วโมงของตัวเองก็ต่อเมื่อเปิดใบอื่นของวันเดียวกัน
	frappe.xcall(
		'truck_service_center.truck_service_center.doctype.service_appointment.service_appointment.get_bay_day_status',
		{
			date: frm.doc.appointment_date,
			exclude_appointment: null
		}
	).then(function(data) {
		if (req !== frm._capacity_req) return;
		// ใบใหม่ยังไม่มีแถวในฐานข้อมูล ชั่วโมงของมันจึงยังไม่อยู่ใน booked
		render_capacity_meter(frm, data, !frm.is_new());
	});
}

function inject_capacity_meter_css() {
	if (document.getElementById('tsc-meter-css')) return;

	const style = document.createElement('style');
	style.id = 'tsc-meter-css';
	style.textContent = `
		.tsc-meter { font-size: 12px; }
		.tsc-meter-head { display: flex; align-items: baseline; gap: 6px; margin-bottom: 6px; }
		.tsc-meter-total { font-size: 15px; font-weight: 600; }
		.tsc-meter-free { margin-left: auto; color: var(--text-muted, #6a7581); }
		/* รายช่องจอดคือข้อมูลที่ต้องอ่านจริงตอนเลือกวัน ไม่ใช่ของประดับ — ให้ขนาดเท่าฟอร์ม
		   และแยกบรรทัดด้วยเส้นจาง แทนการยัดเป็นข้อความ 11px ติดกันจนกวาดตาไม่ทัน */
		.tsc-meter-bay {
			display: flex; align-items: center; gap: 8px;
			padding: 4px 0; border-top: 1px solid var(--border-color, #ebeef0);
		}
		.tsc-meter-bay-name { font-weight: 600; min-width: 72px; }
		.tsc-meter-bay-bar { flex: 1 1 auto; min-width: 40px; height: 6px;
			background: var(--gray-200, #e2e6e9); border-radius: 3px; overflow: hidden; }
		.tsc-meter-bay-bar > span { display: block; height: 100%; }
		.tsc-meter-bay-free { min-width: 74px; text-align: right; font-variant-numeric: tabular-nums; }
		.tsc-meter-bay-type { color: var(--text-muted, #6a7581); font-weight: 400; }
		/* ความจุถูกแบ่งตามประเภทช่องจอดแล้ว ยอดรวมทั้งวันจึงบอกไม่หมดว่าประเภทไหนเต็ม
		   บรรทัดนี้คือสิ่งที่บอก จึงวางไว้ใต้แถบรวมก่อนรายการช่องจอด */
		.tsc-meter-types { color: var(--text-muted, #6a7581); margin-bottom: 4px; }
		.tsc-meter-note { color: var(--text-muted, #6a7581); margin: 6px 0 0; }
	`;
	document.head.appendChild(style);
}

function meter_bar_color(status) {
	return {
		'ว่าง': 'var(--green-500, #29cd42)',
		'ใกล้เต็ม': 'var(--orange-500, #ff8c37)',
		'เต็ม': 'var(--red-500, #ff5858)',
		'ปิดทำการ': 'var(--gray-400, #c0c6cc)'
	}[status] || 'var(--gray-400, #c0c6cc)';
}

function capacity_bay_row_html(bay) {
	const cap = flt(bay.cap);
	const booked = flt(bay.booked);
	// เหลือติดลบแปลว่าช่องนั้นล้นแล้ว แถบเต็มหลอด ตัวเลขบอกส่วนเกินแทน
	const free = flt(bay.free);
	const pct = cap > 0 ? Math.min(Math.max(booked / cap, 0), 1) * 100 : 100;

	let html = '<div class="tsc-meter-bay">';
	html += `<span class="tsc-meter-bay-name">${frappe.utils.escape_html(bay.bay_name || bay.bay)}`;
	if (bay.bay_type) {
		const bay_type = frappe.utils.escape_html(bay.bay_type_name || bay.bay_type);
		html += ` <span class="tsc-meter-bay-type">(${bay_type})</span>`;
	}
	html += '</span>';
	html += `<span class="tsc-meter-bay-bar"><span style="width: ${pct}%; background: ${meter_bar_color(bay.status)};"></span></span>`;

	let right;
	if (bay.is_closed) {
		right = '<span class="text-muted">ปิด</span>';
	} else if (free < 0) {
		right = `<span class="text-danger">เกิน ${fmt_hours(-free)} ชม.</span>`;
	} else {
		right = `เหลือ ${fmt_hours(free)} ชม.`;
	}
	html += `<span class="tsc-meter-bay-free">${right}</span>`;
	html += '</div>';

	if (bay.is_closed && bay.reason) {
		html += `<div class="tsc-meter-note" style="margin: 0 0 2px;">${frappe.utils.escape_html(bay.reason)}</div>`;
	}

	return html;
}

function own_allocated_hours(frm) {
	// อ่านจากตารางที่จัดไว้จริง ไม่ใช่ระยะเวลาทั้งใบ เพราะชั่วโมงของประเภทที่วันนั้นไม่มี
	// ช่องจอดรองรับ จะไม่ถูกจองเข้าไปในวัน (ดู compute_allocation) — ใบที่ยังไม่มีตาราง
	// ตกไปใช้ระยะเวลาทั้งใบ ซึ่งเป็นค่าประมาณที่ดีที่สุดที่มี
	const rows = frm.doc.bay_allocations || [];
	if (rows.length) {
		return rows.reduce(function(sum, row) {
			return sum + flt(row.allocated_hours);
		}, 0);
	}

	return flt(frm.doc.estimated_duration);
}


function render_capacity_meter(frm, data, own_included) {
	const field = frm.get_field('capacity_html');
	if (!field || !data) return;

	inject_capacity_meter_css();

	const summary = data.summary || {};
	const cap = flt(summary.cap);
	const booked = flt(summary.booked);
	const free = flt(summary.free);
	const over = flt(summary.over);
	const own = own_allocated_hours(frm);

	let html = '<div class="tsc-meter">';

	html += '<div class="tsc-meter-head">';
	html += `<span class="tsc-meter-total">${fmt_hours(booked)}/${fmt_hours(cap)} ชม.</span>`;
	if (summary.status) {
		html += `<span class="badge ${bay_status_badge(summary.status)}">${frappe.utils.escape_html(summary.status)}</span>`;
	}
	if (over > 0) {
		html += `<b class="text-danger">เกิน +${fmt_hours(over)}</b>`;
	}
	if (summary.has_bays !== false) {
		html += `<span class="tsc-meter-free">เหลือ ${fmt_hours(free)} ชม.</span>`;
	}
	html += '</div>';

	if (summary.has_bays === false) {
		html += '<p class="text-danger"><b>ยังไม่มีช่องจอดซ่อมที่เปิดใช้งาน</b></p>';
	} else if (data.day_closed) {
		html += '<p class="text-danger"><b>วันนี้ปิดทำการทุกช่องจอด — จองได้แต่จะถือเป็นงาน OT</b></p>';
	}
	if (data.day_note) {
		html += `<p class="tsc-meter-note" style="margin-top: 0;">${frappe.utils.escape_html(data.day_note)}</p>`;
	}

	html += capacity_bar_html(cap, booked, own, summary.status, own_included);
	html += capacity_by_type_html(summary.by_type);

	(data.bays || []).forEach(function(bay) {
		html += capacity_bay_row_html(bay);
	});

	html += '<p class="tsc-meter-note">';
	html += 'ระบบจะจัดช่องจอดให้อัตโนมัติตอนบันทึก แก้ไขเองได้ในตาราง "ช่องจอดที่จัดให้"';
	html += '</p>';

	html += '</div>';

	field.$wrapper.html(html);
}


function capacity_by_type_html(by_type) {
	// งานทั่วไปยืมช่องที่มีหลุมไม่ได้แล้ว ตัวเลขรวมทั้งวันจึงดูว่างกว่าความจริงของแต่ละประเภท
	if (!by_type || !by_type.length) return '';

	const parts = (by_type || []).map(function(group) {
		const name = frappe.utils.escape_html(group.bay_type_name || group.bay_type || '');
		return `${name} ${fmt_hours(group.booked)}/${fmt_hours(group.cap)}`;
	});

	return `<div class="tsc-meter-types">${parts.join(' · ')}</div>`;
}

function capacity_bar_html(cap, booked, own, status, own_included) {
	// ไม่มีความจุให้เทียบ (วันปิด/ไม่มีช่องจอด) — แถบเทาเต็มความกว้างสื่อว่าไม่มีที่ให้วัด
	if (cap <= 0) {
		return '<div class="progress" style="height: 10px; margin-bottom: 8px;">' +
			'<div class="progress-bar bg-secondary" style="width: 100%;"></div></div>';
	}

	const bar_class = {
		'ว่าง': 'bg-success',
		'ใกล้เต็ม': 'bg-warning',
		'เต็ม': 'bg-danger',
		'ปิดทำการ': 'bg-secondary'
	}[status] || 'bg-secondary';

	// ใบที่บันทึกแล้ว ชั่วโมงของตัวเองนับอยู่ใน booked แล้ว — ซอยออกมาเป็นแถบลายให้เห็นว่า
	// ส่วนไหนเป็นของใบนี้ (ความยาวรวมยังเท่ากับ booked) ส่วนใบใหม่ที่ยังไม่บันทึก ชั่วโมง
	// ยังไม่อยู่ใน booked จึงต่อท้ายเป็นส่วนที่ "กำลังจะใช้"
	const own_hours = Math.max(flt(own), 0);
	const base = own_included ? Math.max(booked - own_hours, 0) : booked;

	const booked_pct = Math.min(base / cap, 1) * 100;
	// รวมกันต้องไม่เกิน 100% ของแถบ
	const own_pct = Math.min(own_hours / cap, 1 - booked_pct / 100) * 100;

	let html = '<div class="progress" style="height: 10px; margin-bottom: 8px;">';
	html += `<div class="progress-bar ${bar_class}" style="width: ${booked_pct}%;"></div>`;
	if (own_pct > 0) {
		html += '<div class="progress-bar progress-bar-striped bg-info" ' +
			`style="width: ${own_pct}%;" title="ชั่วโมงของใบนี้"></div>`;
	}
	html += '</div>';

	return html;
}

function capacity_warning_html(warnings) {
	return warnings.map(function(warning) {
		return frappe.utils.escape_html(warning);
	}).join('<br>');
}

function check_appointment_capacity(frm) {
	return frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_appointment.service_appointment.check_appointment_capacity',
		args: {
			doc: JSON.stringify(frm.doc)
		}
	});
}

function clear_bay_allocations(frm) {
	frm.doc.bay_allocations = [];
	frm.refresh_field('bay_allocations');
}

function reallocate_bays(frm) {
	if (!frm.doc.appointment_date) {
		frappe.msgprint(__('กรุณาระบุวันที่นัดหมายก่อน'));
		return;
	}
	
	// ต้องล้างตารางก่อนส่ง ไม่งั้นฝั่ง server จะถือว่าจัดไว้แล้วและไม่จัดใหม่ให้
	clear_bay_allocations(frm);
	
	check_appointment_capacity(frm).then(function(r) {
		if (!r.message) return;
		let allocations = r.message.allocations || [];
		let warnings = r.message.warnings || [];

		allocations.forEach(function(row) {
			let child = frm.add_child('bay_allocations');
			child.service_bay = row.service_bay;
			child.bay_type = row.bay_type;
			child.allocated_hours = row.allocated_hours;
		});
		frm.refresh_field('bay_allocations');
		frm.dirty();

		// payload มี availability มาแล้ว วาด meter จากตรงนี้เลย ไม่ต้องยิง request ซ้ำ
		// วาดหลังเติมตาราง เพื่อให้ส่วน "ของใบนี้" ตรงกับที่เพิ่งจัดให้ ไม่ใช่ของเดิม
		// (availability ชุดนี้ตัดใบนี้ออกไปแล้ว ชั่วโมงของใบนี้จึงยังเป็นส่วนต่อท้าย)
		if (r.message.availability) {
			render_capacity_meter(frm, r.message.availability);
		}
		
		if (allocations.length) {
			frappe.show_alert({
				message: __('จัดช่องจอดใหม่เรียบร้อย — อย่าลืมบันทึกเอกสาร'),
				indicator: 'green'
			});
		} else {
			frappe.show_alert({
				message: __('ยังไม่มีชั่วโมงงานให้จัดช่องจอด'),
				indicator: 'orange'
			});
		}
		
		if (warnings.length) {
			frappe.confirm(
				__('ตรวจพบข้อควรระวังเรื่องช่องจอด:') + '<br><br>' + capacity_warning_html(warnings) +
					'<br><br>' + __('ต้องการใช้การจัดช่องจอดนี้หรือไม่?'),
				function() {
					// ยืนยัน — คงการจัดช่องจอดไว้ตามที่ระบบจัดให้
				},
				function() {
					// ยกเลิก — เคลียร์ตารางกลับว่าง เพื่อให้การบันทึกครั้งถัดไปจัดใหม่เอง
					clear_bay_allocations(frm);
					frappe.show_alert({
						message: __('ยกเลิกการจัดช่องจอด — ตารางถูกล้างแล้ว'),
						indicator: 'orange'
					});
				}
			);
		}
	});
}

function confirm_capacity_before_save(frm) {
	if (frm.doc.docstatus !== 0 || !frm.doc.appointment_date) return;
	
	return check_appointment_capacity(frm).then(function(r) {
		if (r.message && r.message.availability) {
			render_capacity_meter(frm, r.message.availability);
		}

		let warnings = (r.message && r.message.warnings) || [];
		if (!warnings.length) return;
		
		return new Promise(function(resolve, reject) {
			frappe.confirm(
				__('ตรวจพบข้อควรระวังเรื่องความจุช่องจอด:') + '<br><br>' + capacity_warning_html(warnings) +
					'<br><br>' + __('ต้องการบันทึกต่อหรือไม่?'),
				function() {
					resolve();
				},
				function() {
					// return false ไม่หยุดการบันทึก ต้อง reject promise เท่านั้น
					// (pattern เดียวกับ before_service_types_remove ใน service_order.js)
					frappe.show_alert({
						message: __('ยกเลิกการบันทึก'),
						indicator: 'orange'
					});
					reject(new Error('capacity warnings not confirmed'));
				}
			);
		});
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

				// เวลาซ่อมจริงของแพ็คเกจ — ใช้คำนวณระยะเวลานัดหมายด้านล่าง
				row.repair_time_hours = flt(pkg.repair_time_hours);
				
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
					item_row.amount = flt(flt(part.qty) * flt(part.rate), 2);
					item_row.service_package = pkg_name;
					item_row.service_type = part.service_type;
				});
				
				frm.refresh_field('service_packages');
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
						add_service_type_items(frm, items, row.service_type);

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
		// Cascade delete แบบเดียวกับตอนลบแพ็คเกจ — อะไหล่ที่ดึงมาจาก service type
		// ที่ถูกลบไม่ควรค้างอยู่ในนัดหมาย
		remove_orphan_service_type_items(frm);
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

function add_service_type_items(frm, items, service_type) {
	// สร้างแถวใหม่เสมอ ไม่รวม qty เข้าแถวเดิม เพื่อให้อะไหล่ทุกแถวมีที่มาเพียง
	// service type เดียว — ถ้ารวมแถว จะบอกไม่ได้ว่าต้องลบเท่าไหร่ตอนลบ service type
	items.forEach(function(item) {
		let new_row = frm.add_child('service_items');
		new_row.item_code = item.item_code;
		new_row.item_name = item.item_name;
		new_row.qty = item.qty;
		new_row.uom = item.uom;
		new_row.rate = item.rate;
		new_row.amount = flt(flt(item.amount) || flt(item.qty) * flt(item.rate), 2);
		new_row.service_type = service_type;
	});

	frm.refresh_field('service_items');
	calculate_totals(frm);
}

/**
 * ลบอะไหล่ที่ดึงมาจาก service type ซึ่งไม่อยู่ในตารางประเภทบริการแล้ว
 * เก็บอะไหล่ที่เพิ่มเอง (service_type ว่าง) ไว้
 */
function remove_orphan_service_type_items(frm) {
	let remaining = new Set();
	(frm.doc.service_types || []).forEach(function(st) {
		if (st.service_type) {
			remaining.add(st.service_type);
		}
	});

	frm.doc.service_items = (frm.doc.service_items || []).filter(function(si) {
		return !si.service_type || remaining.has(si.service_type);
	});

	frm.doc.service_items.forEach(function(row, idx) { row.idx = idx + 1; });
	frm.refresh_field('service_items');
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
	// สูตรเดียวกับ ServiceAppointment.calculate_estimated_duration ฝั่ง python — ต้องแก้คู่กัน
	// แพ็คเกจที่กรอกเวลาซ่อมจริง (repair_time_hours) ไว้ ใช้ค่านั้นแทนผลรวมเวลาของงานในแพ็คเกจ
	// เพราะงานในแพ็คเกจทำขนานกันได้ ผลรวมจึงยาวเกินจริง
	let by_package = {};
	let loose = 0;
	(frm.doc.service_types || []).forEach(function(row) {
		if (row.service_package) {
			by_package[row.service_package] = flt(by_package[row.service_package]) + flt(row.estimated_time);
		} else {
			loose += flt(row.estimated_time);
		}
	});

	let total = loose;
	(frm.doc.service_packages || []).forEach(function(row) {
		let rows_total = flt(by_package[row.service_package]);
		delete by_package[row.service_package];
		total += flt(row.repair_time_hours) || rows_total;
	});

	// แถวงานที่แพ็คเกจต้นทางถูกลบไปแล้ว ยังต้องนับเวลาให้อยู่
	Object.keys(by_package).forEach(function(key) {
		total += flt(by_package[key]);
	});

	frm.set_value('estimated_duration', flt(total, 2));
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
	frm.set_value('total_labor_charges', flt(total_labor, 2));
	frm.set_value('total_parts_amount', flt(total_parts, 2));
	frm.set_value('total_amount', flt(total_labor + total_parts, 2));
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

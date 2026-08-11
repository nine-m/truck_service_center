// Copyright (c) 2026, Nine-m and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Package', {
	refresh: function(frm) {
		frm.set_query('service_type', 'package_service_types', function() {
			return { filters: { is_active: 1 } };
		});
	},

	package_rate: function(frm) {
		if (frm.doc.total_standard_rate && frm.doc.package_rate) {
			let total = frm.doc.total_standard_rate;
			let package_rate = frm.doc.package_rate;
			if (package_rate > total) {
				// ไม่มีส่วนลด (ตั้งราคาสูงกว่าราคามาตรฐาน) — เตือนอย่างเดียว ไม่บล็อก
				frappe.msgprint({ title: __('Warning'), indicator: 'orange', message: __('ราคาแพ็คเกจสูงกว่าราคามาตรฐาน') });
				frm.set_value('discount_percent', 0);
				return;
			}
			let discount_percent = ((total - package_rate) / total) * 100;
			frm.set_value('discount_percent', discount_percent);
		}
	},

	discount_percent: function(frm) {
		if (frm.doc.total_standard_rate && frm.doc.discount_percent !== undefined) {
			let total = frm.doc.total_standard_rate;
			let dp = frm.doc.discount_percent || 0;
			if (dp > 100 || dp < 0) {
				frappe.msgprint({ title: __('Error'), indicator: 'red', message: __('ส่วนลดต้องอยู่ระหว่าง 0-100%') });
				frm.set_value('discount_percent', 0);
				return;
			}
			frm.set_value('package_rate', total - (total * dp / 100));
		}
	},

	total_standard_rate: function(frm) {
		if (frm.doc.discount_percent) {
			frm.trigger('discount_percent');
		}
	}
});

// === Service Package Service Type child table ===
frappe.ui.form.on('Service Package Service Type', {
	package_service_types_add: function(frm) {
		calculate_package_totals(frm);
	},
	package_service_types_remove: function(frm, cdt, cdn) {
		// ลบอะไหล่ที่ผูกกับ service type ที่ถูกลบ
		rebuild_parts_from_service_types(frm);
		calculate_package_totals(frm);
	},
	service_type: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.service_type) return;

		// ดึงอะไหล่จาก Service Type แล้วเพิ่มลงตาราง package_parts ทันที
		frappe.call({
			method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_service_type_items',
			args: { service_type: row.service_type },
			callback: function(r) {
				if (r.message && r.message.length > 0) {
					r.message.forEach(function(item) {
						let part_row = frm.add_child('package_parts');
						part_row.service_type = row.service_type;
						part_row.item_code = item.item_code;
						part_row.item_name = item.item_name;
						part_row.qty = item.qty;
						part_row.uom = item.uom;
						part_row.rate = item.rate;
						part_row.amount = flt(item.qty) * flt(item.rate);
					});
					frm.refresh_field('package_parts');
				}
				// รอให้ fetch_from labor_rate/estimated_time เสร็จก่อนคำนวณ
				setTimeout(function() {
					calculate_package_totals(frm);
				}, 300);
			}
		});
	},
	labor_rate: function(frm) {
		calculate_package_totals(frm);
	},
	estimated_time: function(frm) {
		calculate_package_totals(frm);
	}
});

// === Service Package Part child table ===
frappe.ui.form.on('Service Package Part', {
	package_parts_add: function(frm) {
		calculate_package_totals(frm);
	},
	package_parts_remove: function(frm) {
		calculate_package_totals(frm);
	},
	qty: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, 'amount', flt(row.qty) * flt(row.rate));
		calculate_package_totals(frm);
	},
	rate: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, 'amount', flt(row.qty) * flt(row.rate));
		calculate_package_totals(frm);
	},
	amount: function(frm) {
		calculate_package_totals(frm);
	}
});

function calculate_package_totals(frm) {
	// ค่าแรงรวม
	let total_labor = 0;
	if (frm.doc.package_service_types) {
		frm.doc.package_service_types.forEach(function(row) {
			total_labor += flt(row.labor_rate);
		});
	}
	frm.set_value('total_labor_rate', total_labor);

	// ค่าอะไหล่รวม
	let total_parts = 0;
	if (frm.doc.package_parts) {
		frm.doc.package_parts.forEach(function(row) {
			total_parts += flt(row.amount);
		});
	}
	frm.set_value('total_parts_amount', total_parts);

	// ราคามาตรฐานรวม
	frm.set_value('total_standard_rate', total_labor + total_parts);
}

/**
 * สร้าง package_parts ใหม่จาก service types ที่ยังอยู่ในตาราง
 * เก็บรายการ manual (ไม่มี service_type) ไว้ ลบเฉพาะ auto ที่ service_type หายไป
 */
function rebuild_parts_from_service_types(frm) {
	// รวบรวม service_type ทั้งหมดที่ยังอยู่
	let active_service_types = new Set();
	(frm.doc.package_service_types || []).forEach(function(row) {
		if (row.service_type) {
			active_service_types.add(row.service_type);
		}
	});

	// กรอง: เก็บ manual parts (ไม่มี service_type) + auto parts ที่ service_type ยังอยู่
	frm.doc.package_parts = (frm.doc.package_parts || []).filter(function(p) {
		return !p.service_type || active_service_types.has(p.service_type);
	});

	// Re-index
	frm.doc.package_parts.forEach(function(row, idx) { row.idx = idx + 1; });
	frm.refresh_field('package_parts');
}

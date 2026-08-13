// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Repair Quotation', {
	onload: function(frm) {
		// ตั้งค่าภาษีเริ่มต้นสำหรับเอกสารใหม่
		if (frm.is_new()) {
			frappe.db.get_value('Truck Service Center Settings', 'Truck Service Center Settings',
				['default_tax_type', 'vat_rate'], function(r) {
					if (r) {
						if (!frm.doc.tax_type) {
							frm.set_value('tax_type', r.default_tax_type || 'ราคาแยก VAT');
						}
						if (!frm.doc.vat_rate) {
							frm.set_value('vat_rate', r.vat_rate || 7);
						}
					}
				}
			);
		}
		calculate_totals(frm);
	},

	refresh: function(frm) {
		// ให้ยอดขยับตั้งแต่ตอนพิมพ์ ไม่ต้องรอออกจากช่อง
		setup_live_row_calc(frm);

		// ตั้งค่า filter ต่างๆ
		setup_service_type_filter(frm);
		setup_service_package_filter(frm);
		set_address_filters(frm);
		set_vehicle_filter(frm);

		// ปุ่ม "สร้าง Service Order"
		if (!frm.is_new() && !frm.doc.service_order
			&& ['Open', 'Accepted', 'Draft'].includes(frm.doc.status)) {
			frm.add_custom_button(__('สร้าง Service Order'), function() {
				// ถ้าสถานะ Draft ให้เปลี่ยนเป็น Open ก่อน
				if (frm.doc.status === 'Draft') {
					frm.set_value('status', 'Open');
					frm.save().then(() => {
						create_service_order(frm);
					});
				} else {
					create_service_order(frm);
				}
			}, __('Actions'));
		}

		// แสดง link ไปยัง Service Order ถ้ามี
		if (frm.doc.service_order) {
			frm.dashboard.add_indicator(
				__('Service Order: {0}', ['<a href="/app/service-order/' + frm.doc.service_order + '">' + frm.doc.service_order + '</a>']),
				'green'
			);
		}

		// ปุ่มเปลี่ยนสถานะ
		if (!frm.is_new()) {
			if (frm.doc.status === 'Draft') {
				frm.add_custom_button(__('เปิดใบเสนอราคา'), function() {
					frm.set_value('status', 'Open');
					frm.save();
				}, __('สถานะ'));
			}

			if (frm.doc.status === 'Open') {
				frm.add_custom_button(__('ลูกค้าอนุมัติ'), function() {
					frm.set_value('status', 'Accepted');
					frm.save();
				}, __('สถานะ'));

				frm.add_custom_button(__('ลูกค้าปฏิเสธ'), function() {
					frm.set_value('status', 'Rejected');
					frm.save();
				}, __('สถานะ'));
			}

			if (['Open', 'Draft'].includes(frm.doc.status)) {
				frm.add_custom_button(__('ยกเลิก'), function() {
					frappe.confirm(
						__('ยืนยันการยกเลิกใบเสนอราคานี้?'),
						function() {
							frm.set_value('status', 'Cancelled');
							frm.save();
						}
					);
				}, __('สถานะ'));
			}
		}

		// แสดงสถานะด้วยสี
		if (frm.doc.status === 'Accepted') {
			frm.dashboard.add_indicator(__('สถานะ: อนุมัติแล้ว'), 'green');
		} else if (frm.doc.status === 'Open') {
			frm.dashboard.add_indicator(__('สถานะ: เปิด'), 'blue');
		} else if (frm.doc.status === 'Rejected') {
			frm.dashboard.add_indicator(__('สถานะ: ปฏิเสธ'), 'red');
		} else if (frm.doc.status === 'Expired') {
			frm.dashboard.add_indicator(__('สถานะ: หมดอายุ'), 'orange');
		} else if (frm.doc.status === 'Cancelled') {
			frm.dashboard.add_indicator(__('สถานะ: ยกเลิก'), 'grey');
		}

		// ล็อคฟอร์มถ้าสถานะเป็น Accepted, Rejected, Expired, Cancelled
		if (['Rejected', 'Expired', 'Cancelled'].includes(frm.doc.status)) {
			frm.disable_save();
			frm.set_read_only();
		}
	},

	customer: function(frm) {
		set_vehicle_filter(frm);
		set_address_filters(frm);

		if (frm.doc.customer) {
			fetch_customer_addresses(frm);
		} else {
			frm.set_value('customer_address', '');
			frm.set_value('address_display', '');
			frm.set_value('shipping_address_name', '');
			frm.set_value('shipping_address', '');
		}

		// ล้างค่ารถถ้าเปลี่ยนลูกค้าและรถไม่ตรง
		if (frm.doc.vehicle) {
			frappe.db.get_value('Vehicle', frm.doc.vehicle, 'customer', function(r) {
				if (r && r.customer !== frm.doc.customer) {
					frm.set_value('vehicle', '');
				}
			});
		}
	},

	customer_address: function(frm) {
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
		if (frm.doc.vehicle) {
			frappe.db.get_value('Vehicle', frm.doc.vehicle,
				['customer', 'current_mileage', 'contact_person', 'contact_number', 'email'],
				function(r) {
					if (r) {
						if (!frm.doc.customer || frm.doc.customer !== r.customer) {
							frm.set_value('customer', r.customer);
						}
						if (r.current_mileage) {
							frm.set_value('current_mileage', r.current_mileage);
						}
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

	// Handler สแกนบาร์โค้ดประเภทบริการ
	scan_service_type_barcode: function(frm) {
		let barcode = frm.doc.scan_service_type_barcode;
		if (!barcode) return;

		frappe.call({
			method: 'frappe.client.get_value',
			args: {
				doctype: 'Service Type',
				filters: { barcode: barcode, is_active: 1 },
				fieldname: ['name', 'service_type_name', 'service_type_group', 'maintenance_type', 'default_duration', 'labor_rate']
			},
			callback: function(r) {
				frm.set_value('scan_service_type_barcode', '');

				if (r.message && r.message.name) {
					let data = r.message;

					// ตรวจสอบซ้ำ
					let exists = (frm.doc.service_types || []).some(row => row.service_type === data.name);
					if (exists) {
						frappe.show_alert({
							message: __('ประเภทบริการ "{0}" มีอยู่แล้ว', [data.service_type_name]),
							indicator: 'orange'
						});
						return;
					}

					let row = frm.add_child('service_types');
					row.service_type = data.name;
					row.service_type_group = data.service_type_group;
					row.maintenance_type = data.maintenance_type;
					row.estimated_time = data.default_duration || 0;
					row.labor_charges = data.labor_rate || 0;

					frm.refresh_field('service_types');
					calculate_totals(frm);

					frappe.show_alert({
						message: __('เพิ่มประเภทบริการ "{0}" เรียบร้อย', [data.service_type_name]),
						indicator: 'green'
					});

					// ตรวจสอบและเพิ่มอะไหล่ที่ผูกกับ service type
					check_and_add_service_type_items(frm, data.name);
				} else {
					frappe.show_alert({
						message: __('ไม่พบประเภทบริการจากบาร์โค้ด "{0}"', [barcode]),
						indicator: 'red'
					});
				}
			}
		});
	},

	// Handler สแกนบาร์โค้ดอะไหล่
	scan_item_barcode: function(frm) {
		let barcode = frm.doc.scan_item_barcode;
		if (!barcode) return;

		frappe.call({
			method: 'truck_service_center.truck_service_center.doctype.repair_quotation.repair_quotation.get_item_by_barcode',
			args: {
				barcode: barcode,
				customer: frm.doc.customer
			},
			callback: function(r) {
				frm.set_value('scan_item_barcode', '');

				if (r.message && r.message.item_code) {
					let item_data = r.message;

					// ค้นหารายการที่มี item_code เดียวกัน
					let existing_row = (frm.doc.service_items || []).find(
						row => row.item_code === item_data.item_code
					);

					if (existing_row) {
						let new_qty = flt(existing_row.qty) + 1;
						frappe.model.set_value(existing_row.doctype, existing_row.name, 'qty', new_qty);
						frm.refresh_field('service_items');
						calculate_totals(frm);

						frappe.show_alert({
							message: __('เพิ่มจำนวน "{0}" เป็น {1}', [item_data.item_name, new_qty]),
							indicator: 'green'
						});
					} else {
						let row = frm.add_child('service_items');
						row.item_code = item_data.item_code;
						row.item_name = item_data.item_name;
						row.description = item_data.description;
						row.uom = item_data.uom;
						row.qty = 1;
						row.rate = item_data.rate || 0;
						row.amount = item_data.rate || 0;

						frm.refresh_field('service_items');
						calculate_totals(frm);

						frappe.show_alert({
							message: __('เพิ่มอะไหล่ "{0}" เรียบร้อย', [item_data.item_name]),
							indicator: 'green'
						});

						if (!item_data.rate || item_data.rate === 0) {
							frappe.show_alert({
								message: __('ไม่พบราคาสำหรับสินค้านี้ กรุณาตั้งค่า Item Price'),
								indicator: 'orange'
							});
						}
					}
				} else {
					frappe.show_alert({
						message: __('ไม่พบสินค้าจากบาร์โค้ด "{0}"', [barcode]),
						indicator: 'red'
					});
				}
			}
		});
	},

	discount_amount: function(frm) {
		calculate_totals(frm);
	},

	tax_type: function(frm) {
		calculate_totals(frm);
	},

	vat_rate: function(frm) {
		calculate_totals(frm);
	}
});


// === Child Table: Repair Quotation Package ===
frappe.ui.form.on('Repair Quotation Package', {
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
					st_row.discount_percentage = discount_pct;
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
					item_row.discount_percentage = discount_pct;
					item_row.service_package = pkg_name;
				});
				
				frm.refresh_field('service_types');
				frm.refresh_field('service_items');
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
		calculate_totals(frm);
	}
});

// === Child Table: Repair Quotation Service Type ===
frappe.ui.form.on('Repair Quotation Service Type', {
	service_types_add: function(frm) {
		calculate_totals(frm);
	},

	service_types_remove: function(frm) {
		calculate_totals(frm);
	},

	service_type: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.service_type) {
			// ตรวจสอบว่ามีอะไหล่มาตรฐานหรือไม่
			frappe.call({
				method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_service_type_items',
				args: { service_type: row.service_type },
				callback: function(r) {
					if (r.message && r.message.length > 0) {
						let items = r.message;
						let item_list = items.map(item =>
							`• ${item.item_name || item.item_code} - จำนวน: ${item.qty} ${item.uom || ''} (฿${item.rate || 0})`
						).join('<br>');

						frappe.confirm(
							__('ประเภทบริการ "{0}" มีรายการอะไหล่มาตรฐาน {1} รายการ:<br><br>{2}<br><br>ต้องการเพิ่มรายการอะไหล่เหล่านี้หรือไม่?',
								[row.service_type, items.length, item_list]),
							function() {
								add_service_type_items(frm, items, row.service_type);
							}
						);
					}
				}
			});
		}
	},

	labor_charges: function(frm, cdt, cdn) {
		calculate_service_type_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	discount_percentage: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (flt(row.discount_percentage) > 0) {
			let discount_amt = flt(flt(row.labor_charges) * flt(row.discount_percentage) / 100, 2);
			frappe.model.set_value(cdt, cdn, 'discount_amount', discount_amt);
		} else {
			frappe.model.set_value(cdt, cdn, 'discount_amount', 0);
		}
		calculate_service_type_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	discount_amount: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (flt(row.discount_amount) > 0 && flt(row.labor_charges) > 0) {
			let pct = flt(flt(row.discount_amount) / flt(row.labor_charges) * 100, 2);
			frappe.model.set_value(cdt, cdn, 'discount_percentage', pct);
		} else if (flt(row.discount_amount) === 0) {
			frappe.model.set_value(cdt, cdn, 'discount_percentage', 0);
		}
		calculate_service_type_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	estimated_time: function(frm) {
		calculate_totals(frm);
	}
});


// === Child Table: Repair Quotation Item ===
frappe.ui.form.on('Repair Quotation Item', {
	service_items_add: function(frm) {
		calculate_totals(frm);
	},

	service_items_remove: function(frm) {
		calculate_totals(frm);
	},

	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.item_code) {
			frappe.call({
				method: 'truck_service_center.truck_service_center.doctype.repair_quotation.repair_quotation.get_item_rate',
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

						// สรุปยอดทันทีที่เลือกอะไหล่ ไม่ต้องรอ trigger ของ rate
						// (frappe.model.set_value จะไม่ยิง trigger ถ้าค่าใหม่เท่าค่าเดิม)
						calculate_item_amount(frm, cdt, cdn);
						calculate_totals(frm);

						if (!r.message.rate || r.message.rate === 0) {
							frappe.show_alert({
								message: __('ไม่พบราคาสำหรับสินค้านี้ กรุณาตั้งค่า Item Price'),
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

	discount_percentage: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (flt(row.discount_percentage) > 0) {
			let discount_amt = flt(flt(row.rate) * flt(row.discount_percentage) / 100, 2);
			frappe.model.set_value(cdt, cdn, 'discount_amount', discount_amt);
		} else {
			frappe.model.set_value(cdt, cdn, 'discount_amount', 0);
		}
		calculate_item_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	discount_amount: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (flt(row.discount_amount) > 0 && flt(row.rate) > 0 && !flt(row.discount_percentage)) {
			let pct = flt(flt(row.discount_amount) / flt(row.rate) * 100, 2);
			frappe.model.set_value(cdt, cdn, 'discount_percentage', pct);
		}
		calculate_item_amount(frm, cdt, cdn);
		calculate_totals(frm);
	}
});


// ============ Helper Functions ============

function create_service_order(frm) {
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.repair_quotation.repair_quotation.create_service_order_from_quotation',
		args: {
			repair_quotation: frm.doc.name
		},
		freeze: true,
		freeze_message: __('กำลังสร้าง Service Order...'),
		callback: function(r) {
			if (r.message) {
				frm.reload_doc();
				frappe.set_route('Form', 'Service Order', r.message);
			}
		}
	});
}

function calculate_item_amount(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let values = get_item_amounts(row);
	set_row_value(row, 'discount_amount', values.discount_amount);
	set_row_value(row, 'amount', values.amount);
}

function calculate_service_type_amount(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let values = get_service_type_amounts(row);
	set_row_value(row, 'discount_amount', values.discount_amount);
	set_row_value(row, 'amount', values.amount);
}

// ปกติ Frappe จะคำนวณให้ตอน "ออกจากช่อง" (event change) เท่านั้น
// สองฟังก์ชันนี้ทำให้ยอดในแถวและยอดรวมท้ายเอกสารขยับตั้งแต่ตอนพิมพ์
function setup_live_row_calc(frm) {
	bind_live_row_calc(frm, 'service_items', ['qty', 'rate'], calculate_item_amount);
	bind_live_row_calc(frm, 'service_types', ['labor_charges', 'estimated_time'], calculate_service_type_amount);
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
		recalc_row(frm, cdt, cdn);
		calculate_totals(frm);
	});
}

// เขียนค่าลงแถวผ่าน model เพื่อให้ช่องในตารางรีเฟรชทันที
//
// สำคัญ: ห้ามแก้ค่าใน row เองก่อนเรียก frappe.model.set_value เด็ดขาด
// เพราะ set_value จะเทียบค่าใหม่กับค่าใน model ถ้าเท่ากันจะถือว่า "ไม่มีอะไรเปลี่ยน"
// แล้วไม่ยิง event ที่ทำให้ grid วาดช่องใหม่ (ตัวเลขในตารางจะค้างจนกว่าจะ refresh ทั้งตาราง)
function set_row_value(row, fieldname, value) {
	if (locals[row.doctype] && locals[row.doctype][row.name]) {
		frappe.model.set_value(row.doctype, row.name, fieldname, value);
	} else {
		row[fieldname] = value;
	}
}

// คำนวณส่วนลดระดับบรรทัดของอะไหล่ — คืนค่าใหม่โดยไม่แก้ค่าใน item
function get_item_amounts(item) {
	let rate = flt(item.rate);
	let qty = flt(item.qty);
	let discount_percentage = flt(item.discount_percentage);
	let discount_amount = flt(item.discount_amount);

	if (discount_percentage > 0) {
		discount_amount = flt(rate * discount_percentage / 100, 2);
	} else if (discount_amount > 0 && rate > 0) {
		discount_percentage = flt(discount_amount / rate * 100, 2);
	}

	let net_rate = flt(rate - discount_amount, 2);
	if (net_rate < 0) net_rate = 0;

	return {
		discount_percentage: discount_percentage,
		discount_amount: discount_amount,
		amount: flt(net_rate * qty, 2)
	};
}

// คำนวณส่วนลดระดับบรรทัดของค่าแรง — คืนค่าใหม่โดยไม่แก้ค่าใน row
function get_service_type_amounts(row) {
	let labor = flt(row.labor_charges);
	let discount_percentage = flt(row.discount_percentage);
	let discount_amount = flt(row.discount_amount);

	if (discount_percentage > 0) {
		discount_amount = flt(labor * discount_percentage / 100, 2);
	} else if (discount_amount > 0 && labor > 0) {
		discount_percentage = flt(discount_amount / labor * 100, 2);
	}

	let net_labor = flt(labor - discount_amount, 2);
	if (net_labor < 0) net_labor = 0;

	return {
		discount_percentage: discount_percentage,
		discount_amount: discount_amount,
		amount: flt(net_labor, 2)
	};
}

function calculate_totals(frm) {
	// คำนวณค่าแรงรวมและเวลาประมาณการรวม
	let total_labor = 0;
	let total_time = 0;

	if (frm.doc.service_types) {
		frm.doc.service_types.forEach(function(row) {
			let values = get_service_type_amounts(row);
			// เขียนผ่าน model เพื่อให้ช่อง "ยอดรวม" ของแถวนั้นอัปเดตทันที
			set_row_value(row, 'amount', values.amount);
			total_labor += flt(values.amount);
			total_time += flt(row.estimated_time);
		});
	}

	frm.set_value('labor_charges', total_labor);
	frm.set_value('estimated_time', total_time);

	// คำนวณยอดรวมอะไหล่
	let total_parts = 0;
	if (frm.doc.service_items) {
		frm.doc.service_items.forEach(function(item) {
			let values = get_item_amounts(item);
			// เขียนผ่าน model เพื่อให้ช่อง "ยอดรวม" ของแถวนั้นอัปเดตทันที
			set_row_value(item, 'amount', values.amount);
			total_parts += flt(values.amount);
		});
	}
	frm.set_value('total_parts_amount', total_parts);

	// คำนวณยอดก่อนภาษี
	let subtotal = total_parts + total_labor - flt(frm.doc.discount_amount);

	// คำนวณภาษีตามประเภท
	let tax_type = frm.doc.tax_type;
	let vat_rate = flt(frm.doc.vat_rate);
	let net_total = 0;
	let tax_amount = 0;
	let total = 0;

	if (tax_type === 'ราคารวม VAT' && vat_rate) {
		tax_amount = flt(subtotal * vat_rate / (100 + vat_rate), 2);
		net_total = flt(subtotal - tax_amount, 2);
		total = flt(subtotal, 2);
	} else if (tax_type === 'ราคาแยก VAT' && vat_rate) {
		net_total = flt(subtotal, 2);
		tax_amount = flt(subtotal * vat_rate / 100, 2);
		total = flt(net_total + tax_amount, 2);
	} else {
		net_total = flt(subtotal, 2);
		tax_amount = 0;
		total = flt(subtotal, 2);
	}

	frm.set_value('net_total', net_total);
	frm.set_value('tax_amount', tax_amount);
	frm.set_value('total_amount', total);
}

function setup_service_package_filter(frm) {
	frm.set_query('service_package', 'service_packages', function() {
		return {
			filters: { 'is_active': 1 }
		};
	});
}

function setup_service_type_filter(frm) {
	frm.set_query('service_type', 'service_types', function(doc, cdt, cdn) {
		let row = locals[cdt][cdn];
		let filters = { 'is_active': 1 };
		if (row.service_type_group) {
			filters['service_type_group'] = row.service_type_group;
		}
		return { filters: filters };
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
				filters: { 'status': 'Active' }
			};
		});
	}
}

function set_address_filters(frm) {
	if (frm.doc.customer) {
		let filter_fn = function() {
			return {
				query: 'frappe.contacts.doctype.address.address.address_query',
				filters: {
					link_doctype: 'Customer',
					link_name: frm.doc.customer
				}
			};
		};
		frm.set_query('customer_address', filter_fn);
		frm.set_query('shipping_address_name', filter_fn);
	}
}

function fetch_customer_addresses(frm) {
	// ดึง default billing address
	frappe.call({
		method: 'frappe.contacts.doctype.address.address.get_default_address',
		args: {
			doctype: 'Customer',
			name: frm.doc.customer
		},
		callback: function(r) {
			if (r.message) {
				frm.set_value('customer_address', r.message);
			}
		}
	});

	// ดึง default shipping address
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_party_shipping_address',
		args: {
			doctype: 'Customer',
			name: frm.doc.customer
		},
		callback: function(r) {
			if (r.message) {
				frm.set_value('shipping_address_name', r.message);
			}
		}
	});
}

function check_and_add_service_type_items(frm, service_type) {
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_service_type_items',
		args: { service_type: service_type },
		callback: function(r) {
			if (r.message && r.message.length > 0) {
				let items = r.message;
				let item_list = items.map(item =>
					`• ${item.item_name || item.item_code} - จำนวน: ${item.qty} ${item.uom || ''} (฿${item.rate || 0})`
				).join('<br>');

				frappe.confirm(
					__('ประเภทบริการ "{0}" มีรายการอะไหล่มาตรฐาน {1} รายการ:<br><br>{2}<br><br>ต้องการเพิ่มรายการอะไหล่เหล่านี้หรือไม่?',
						[service_type, items.length, item_list]),
					function() {
						add_service_type_items(frm, items, service_type);
					}
				);
			}
		}
	});
}

function add_service_type_items(frm, items, service_type) {
	let added_count = 0;

	items.forEach(function(item) {
		let exists = false;
		if (frm.doc.service_items) {
			for (let i = 0; i < frm.doc.service_items.length; i++) {
				if (frm.doc.service_items[i].item_code === item.item_code) {
					frm.doc.service_items[i].qty += item.qty;
					frm.doc.service_items[i].amount = frm.doc.service_items[i].qty * frm.doc.service_items[i].rate;
					exists = true;
					added_count++;
					break;
				}
			}
		}

		if (!exists) {
			let new_row = frm.add_child('service_items');
			new_row.item_code = item.item_code;
			new_row.item_name = item.item_name;
			new_row.description = item.description;
			new_row.qty = item.qty;
			new_row.uom = item.uom;
			new_row.rate = item.rate;
			new_row.amount = item.amount || (item.qty * item.rate);
			added_count++;
		}
	});

	frm.refresh_field('service_items');
	calculate_totals(frm);

	frappe.show_alert({
		message: __('เพิ่มรายการอะไหล่ {0} รายการจาก "{1}" เรียบร้อย', [added_count, service_type]),
		indicator: 'green'
	});
}

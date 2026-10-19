// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Order", {
	onload: function (frm) {
		// ตั้งค่า filter สำหรับช่างผู้รับผิดชอบ
		set_technician_filter(frm);

		// ตั้งค่า filter สำหรับช่องจอด (เฉพาะที่เปิดใช้งาน)
		set_bay_filter(frm);

		// ค่าตั้งต้นของช่องจอดหลัก ใช้คืนค่าเมื่อผู้ใช้ยกเลิกที่หน้าต่างเตือน
		frm.__previous_bay = frm.doc.service_bay || null;

		// ตั้งค่าภาษีเริ่มต้นสำหรับเอกสารใหม่
		if (frm.is_new()) {
			frappe.db.get_value(
				"Truck Service Center Settings",
				"Truck Service Center Settings",
				["default_tax_type", "vat_rate"],
				function (r) {
					if (r) {
						if (!frm.doc.tax_type) {
							frm.set_value("tax_type", r.default_tax_type || "ราคาแยก VAT");
						}
						if (!frm.doc.vat_rate) {
							frm.set_value("vat_rate", r.vat_rate || 7);
						}
					}
				}
			);
		}
		// คำนวณยอดรวมเมื่อโหลดครั้งแรก
		calculate_totals(frm);
	},

	refresh: function (frm) {
		// ให้ยอดขยับตั้งแต่ตอนพิมพ์ ไม่ต้องรอออกจากช่อง
		setup_live_row_calc(frm);

		// ตั้งค่า filter สำหรับ service_type ใน child table
		setup_service_type_filter(frm);

		// ตั้งค่า filter สำหรับ service_package ในตาราง packages
		setup_service_package_filter(frm);

		// ปุ่มแนะนำแพ็คเกจ PM ตามเลขไมล์/ชั่วโมงทำงาน (public/js/pm_package_dialog.bundle.js)
		truck_service_center.pm.add_button(frm);

		// ตั้งค่า filter สำหรับ address ตาม customer
		set_address_filters(frm);

		// แสดงสรุป Material Issues
		show_material_issue_summary(frm);

		// Update สถานะ Material Issue ทั้งหมด
		update_material_issue_statuses(frm);

		// ป้องกันการแก้ไขแถวที่มี Material Issue ที่ submit แล้ว
		lock_rows_with_submitted_material_issue(frm);

		// หัวหน้าช่าง/ผู้ดูแลระบบคีย์เวลาเริ่ม-จบของงานเองได้ (เช่นคีย์ย้อนหลังงานนอกเวลาทำการ)
		allow_work_time_editing(frm);
		add_work_time_button(frm);
		show_manual_work_time_notice(frm);

		// ปุ่มสร้าง Material Issue (สำหรับ items ที่ยังไม่มีใบเบิก)
		// ต้องรับรถก่อนถึงจะเบิกอะไหล่ได้ — ถ้ายังไม่รับรถจะเห็นแค่ปุ่ม "รับรถ"
		if (
			frm.doc.docstatus === 0 &&
			(frm.doc.received_date || frm.doc.status === "In Progress") &&
			frm.doc.service_items &&
			frm.doc.service_items.length > 0
		) {
			// ตรวจสอบว่ามี item ที่ยังไม่มี Material Issue หรือไม่
			let has_unlinked_items = frm.doc.service_items.some(
				(item) => !item.material_issue && item.item_code
			);

			if (has_unlinked_items) {
				frm.add_custom_button(
					__("Create Material Issue"),
					function () {
						create_material_issue_dialog(frm);
					},
					__("Actions")
				);
			}
		}

		// ปุ่มสร้าง Sales Invoice
		if (frm.doc.docstatus === 1 && !frm.doc.sales_invoice) {
			frm.add_custom_button(__("Create Sales Invoice"), function () {
				frappe.call({
					method: "truck_service_center.truck_service_center.doctype.service_order.service_order.create_sales_invoice_from_service_order",
					args: {
						service_order: frm.doc.name,
					},
					callback: function (r) {
						if (r.message) {
							frappe.msgprint(__("Sales Invoice {0} created", [r.message]));
							frm.reload_doc();
						}
					},
				});
			});
		}

		// ปุ่มรับชำระเงิน — เมื่อ submit แล้ว มี Sales Invoice และยังชำระไม่ครบ
		// สร้าง Payment Entry (draft) แล้วพาไปหน้า Payment Entry เพื่อตรวจสอบ/Submit
		// เมื่อ Payment Entry ถูก Submit สถานะการชำระเงินจะซิงค์กลับมาอัตโนมัติ
		if (
			frm.doc.docstatus === 1 &&
			frm.doc.sales_invoice &&
			frm.doc.payment_status !== "Paid"
		) {
			frm.add_custom_button(__("รับชำระเงิน"), function () {
				frappe.call({
					method: "truck_service_center.truck_service_center.doctype.service_order.service_order.create_payment_entry",
					args: {
						service_order: frm.doc.name,
					},
					callback: function (r) {
						if (r.message) {
							frappe.set_route("Form", "Payment Entry", r.message);
						}
					},
				});
			}).addClass("btn-primary");
		}

		// แสดงสถานะด้วยสี
		if (frm.doc.status === "Completed") {
			frm.dashboard.add_indicator(__("Status: Completed"), "green");
		} else if (frm.doc.status === "Ready for Delivery") {
			frm.dashboard.add_indicator(__("Status: Ready for Delivery"), "blue");
		} else if (frm.doc.status === "In Progress") {
			frm.dashboard.add_indicator(__("Status: In Progress"), "orange");
		} else if (frm.doc.status === "On Hold") {
			frm.dashboard.add_indicator(__("Status: On Hold"), "red");
		}

		// ตั้งค่า filter สำหรับ vehicle ตาม customer
		set_vehicle_filter(frm);

		// ปุ่มรับรถ — แสดงเฉพาะเมื่อสถานะเป็น Draft และยังไม่ submit
		if (frm.doc.docstatus === 0 && frm.doc.status === "Draft") {
			frm.add_custom_button(__("รับรถ"), function () {
				// ตรวจสอบว่ากรอกสถานะน้ำมันรับเข้าแล้วหรือยัง
				if (!frm.doc.fuel_level_in) {
					frappe.msgprint({
						title: __("ไม่สามารถรับรถได้"),
						indicator: "red",
						message: __("กรุณากรอกสถานะน้ำมันรับเข้าก่อนทำการรับรถ"),
					});
					return;
				}

				// เรียก receive_vehicle หลังจากแน่ใจว่าเอกสารถูกบันทึกแล้ว
				const do_receive = function () {
					frappe.call({
						method: "truck_service_center.truck_service_center.doctype.service_order.service_order.receive_vehicle",
						args: { service_order: frm.doc.name },
						callback: function (r) {
							if (!r.exc) {
								frm.reload_doc();
								frappe.show_alert({
									message: __("รับรถเรียบร้อยแล้ว"),
									indicator: "green",
								});
							}
						},
					});
				};

				frappe.confirm(__("ยืนยันการรับรถ?"), function () {
					// ถ้ามีการแก้ไขที่ยังไม่บันทึก (เช่น แก้น้ำมัน) ให้ save ให้อัตโนมัติก่อนรับรถ
					if (frm.is_dirty()) {
						frm.save().then(do_receive);
					} else {
						do_receive();
					}
				});
			}).addClass("btn-primary");
		}

		// ปุ่มเปลี่ยนสถานะเหมือนในพอร์ทัลช่าง — ช่องสถานะเลือกเองไม่ได้แล้ว
		add_status_buttons(frm);
	},

	customer: function (frm) {
		// เมื่อเลือก customer ให้ filter รถของลูกค้านั้น
		set_vehicle_filter(frm);

		// ตั้งค่า filter สำหรับ address ตาม customer
		set_address_filters(frm);

		// ดึง default billing/shipping address ของลูกค้า
		if (frm.doc.customer) {
			fetch_customer_addresses(frm);

			// ลูกค้านิติบุคคล → ติ๊กหักภาษี ณ ที่จ่ายให้อัตโนมัติ (ผู้ใช้เอาออกได้)
			if (frm.doc.docstatus === 0 && !frm.doc.apply_wht) {
				frappe.db.get_value("Customer", frm.doc.customer, "customer_type", function (r) {
					if (r && r.customer_type === "Company") {
						frm.set_value("apply_wht", 1);
					}
				});
			}
		} else {
			// ล้างค่า address ถ้าไม่มีลูกค้า
			frm.set_value("customer_address", "");
			frm.set_value("address_display", "");
			frm.set_value("shipping_address_name", "");
			frm.set_value("shipping_address", "");
		}

		// ล้างค่ารถถ้าเปลี่ยนลูกค้าและรถที่เลือกไว้ไม่ใช่ของลูกค้านี้
		if (frm.doc.vehicle) {
			frappe.db.get_value("Vehicle", frm.doc.vehicle, "customer", function (r) {
				if (r && r.customer !== frm.doc.customer) {
					frm.set_value("vehicle", "");
				}
			});
		}
	},

	customer_address: function (frm) {
		// เมื่อเลือก billing address ให้ render address display
		if (frm.doc.customer_address) {
			frappe.call({
				method: "frappe.contacts.doctype.address.address.get_address_display",
				args: { address_dict: frm.doc.customer_address },
				callback: function (r) {
					if (r.message) {
						frm.set_value("address_display", r.message);
					}
				},
			});
		} else {
			frm.set_value("address_display", "");
		}
	},

	shipping_address_name: function (frm) {
		// เมื่อเลือก shipping address ให้ render address display
		if (frm.doc.shipping_address_name) {
			frappe.call({
				method: "frappe.contacts.doctype.address.address.get_address_display",
				args: { address_dict: frm.doc.shipping_address_name },
				callback: function (r) {
					if (r.message) {
						frm.set_value("shipping_address", r.message);
					}
				},
			});
		} else {
			frm.set_value("shipping_address", "");
		}
	},

	vehicle: function (frm) {
		// ดึงข้อมูลลูกค้าและข้อมูลติดต่อจากรถ
		if (frm.doc.vehicle) {
			frappe.db.get_value(
				"Vehicle",
				frm.doc.vehicle,
				["customer", "current_mileage", "contact_person", "contact_number", "email"],
				function (r) {
					if (r) {
						// ถ้ายังไม่ได้เลือกลูกค้า หรือลูกค้าไม่ตรง ให้เซ็ตลูกค้าใหม่
						if (!frm.doc.customer || frm.doc.customer !== r.customer) {
							frm.set_value("customer", r.customer);
						}
						// ดึงเลขไมล์ปัจจุบัน (ดึงทุกครั้งเพื่ออัพเดทเป็นค่าล่าสุด)
						if (r.current_mileage) {
							frm.set_value("current_mileage", r.current_mileage);
						}
						// ดึงข้อมูลติดต่อ (ถ้ายังไม่ได้กรอก)
						if (r.contact_person && !frm.doc.contact_person) {
							frm.set_value("contact_person", r.contact_person);
						}
						if (r.contact_number && !frm.doc.contact_number) {
							frm.set_value("contact_number", r.contact_number);
						}
						if (r.email && !frm.doc.email) {
							frm.set_value("email", r.email);
						}
					}
				}
			);
		}
	},

	// Handler สำหรับสแกนบาร์โค้ดประเภทบริการ
	scan_service_type_barcode: function (frm) {
		let barcode = frm.doc.scan_service_type_barcode;
		if (!barcode) return;

		// ค้นหา Service Type จากบาร์โค้ด
		frappe.call({
			method: "frappe.client.get_value",
			args: {
				doctype: "Service Type",
				filters: { barcode: barcode, is_active: 1 },
				fieldname: [
					"name",
					"service_type_name",
					"service_type_group",
					"maintenance_type",
					"default_duration",
					"labor_rate",
				],
			},
			callback: function (r) {
				// ล้างช่องสแกนก่อน
				frm.set_value("scan_service_type_barcode", "");

				if (r.message && r.message.name) {
					let service_type_data = r.message;

					// ตรวจสอบว่ามี Service Type นี้อยู่แล้วหรือไม่
					let exists = false;
					if (frm.doc.service_types) {
						for (let i = 0; i < frm.doc.service_types.length; i++) {
							if (frm.doc.service_types[i].service_type === service_type_data.name) {
								exists = true;
								break;
							}
						}
					}

					if (exists) {
						frappe.show_alert({
							message: __('ประเภทบริการ "{0}" มีอยู่แล้วในรายการ', [
								service_type_data.service_type_name,
							]),
							indicator: "orange",
						});
						return;
					}

					// เพิ่ม Service Type ใหม่
					let row = frm.add_child("service_types");
					row.service_type = service_type_data.name;
					row.service_type_group = service_type_data.service_type_group;
					row.maintenance_type = service_type_data.maintenance_type;
					row.estimated_time = service_type_data.default_duration || 0;
					row.labor_charges = service_type_data.labor_rate || 0;

					frm.refresh_field("service_types");
					calculate_totals(frm);

					frappe.show_alert({
						message: __('เพิ่มประเภทบริการ "{0}" เรียบร้อย', [
							service_type_data.service_type_name,
						]),
						indicator: "green",
					});

					// ตรวจสอบว่ามีรายการอะไหล่ที่ผูกไว้หรือไม่
					check_and_add_service_type_items(frm, service_type_data.name);
				} else {
					frappe.show_alert({
						message: __('ไม่พบประเภทบริการที่ตรงกับบาร์โค้ด "{0}"', [barcode]),
						indicator: "red",
					});
				}
			},
		});
	},

	// Handler สำหรับสแกนบาร์โค้ดอะไหล่
	scan_item_barcode: function (frm) {
		let barcode = frm.doc.scan_item_barcode;
		if (!barcode) return;

		// ค้นหา Item จากบาร์โค้ด (ใช้ฟิลด์ barcodes ของ Item)
		frappe.call({
			method: "truck_service_center.truck_service_center.doctype.service_order.service_order.get_item_by_barcode",
			args: {
				barcode: barcode,
				customer: frm.doc.customer,
			},
			callback: function (r) {
				// ล้างช่องสแกนก่อน
				frm.set_value("scan_item_barcode", "");

				if (r.message && r.message.item_code) {
					let item_data = r.message;

					// ค้นหารายการที่มี item_code เดียวกันและยังไม่มี material_issue
					let existing_row = null;
					if (frm.doc.service_items) {
						for (let i = 0; i < frm.doc.service_items.length; i++) {
							let row = frm.doc.service_items[i];
							// หารายการที่ item_code ตรงกัน และยังไม่มีใบเบิก
							if (row.item_code === item_data.item_code && !row.material_issue) {
								existing_row = row;
								break;
							}
						}
					}

					if (existing_row) {
						// มีรายการที่ยังไม่มีใบเบิก ให้เพิ่มจำนวน
						let new_qty = flt(existing_row.qty) + 1;
						frappe.model.set_value(
							existing_row.doctype,
							existing_row.name,
							"qty",
							new_qty
						);

						// คำนวณยอดเงินใหม่
						let new_amount = new_qty * flt(existing_row.rate);
						frappe.model.set_value(
							existing_row.doctype,
							existing_row.name,
							"amount",
							new_amount
						);

						frm.refresh_field("service_items");
						calculate_totals(frm);

						frappe.show_alert({
							message: __('เพิ่มจำนวน "{0}" เป็น {1}', [
								item_data.item_name,
								new_qty,
							]),
							indicator: "green",
						});
					} else {
						// ไม่มีรายการที่ไม่มีใบเบิก หรือเป็นรายการใหม่ ให้สร้างแถวใหม่
						let row = frm.add_child("service_items");
						row.item_code = item_data.item_code;
						row.item_name = item_data.item_name;
						row.description = item_data.description;
						row.uom = item_data.uom;
						row.qty = 1;
						row.rate = item_data.rate || 0;
						row.amount = item_data.rate || 0;

						frm.refresh_field("service_items");
						calculate_totals(frm);

						frappe.show_alert({
							message: __('เพิ่มอะไหล่ "{0}" เรียบร้อย', [item_data.item_name]),
							indicator: "green",
						});

						// แสดงข้อความถ้าราคาเป็น 0
						if (!item_data.rate || item_data.rate === 0) {
							frappe.show_alert({
								message: __("ไม่พบราคาสำหรับสินค้านี้ กรุณาตั้งค่า Item Price"),
								indicator: "orange",
							});
						}
					}
				} else {
					frappe.show_alert({
						message: __('ไม่พบสินค้าที่ตรงกับบาร์โค้ด "{0}"', [barcode]),
						indicator: "red",
					});
				}
			},
		});
	},

	service_bay: function (frm) {
		// เติมแถวที่ยังไม่ระบุช่องจอดให้ทันที แล้วเตือนถ้าชนกับใบอื่น/งานต้องใช้หลุม
		fill_empty_row_bays(frm);

		// จำค่าก่อนหน้าไว้เอง เพราะ frappe ไม่ได้ส่งค่าเดิมเข้ามาใน trigger
		let previous = frm.__previous_bay || null;
		frm.__previous_bay = frm.doc.service_bay || null;

		if (!frm.doc.service_bay || frm.is_new()) return;

		confirm_bay_change(frm, { service_bay: frm.doc.service_bay }, function () {
			frm.__previous_bay = previous;
			frm.set_value("service_bay", previous);
		});
	},

	labor_charges: function (frm) {
		calculate_totals(frm);
	},

	discount_amount: function (frm) {
		calculate_totals(frm);
	},

	tax_type: function (frm) {
		calculate_totals(frm);
	},

	apply_wht: function (frm) {
		calculate_totals(frm);
	},

	wht_rate: function (frm) {
		calculate_totals(frm);
	},

	wht_base: function (frm) {
		calculate_totals(frm);
	},

	vat_rate: function (frm) {
		calculate_totals(frm);
	},

	paid_amount: function (frm) {
		calculate_totals(frm);
	},

	before_save: function (frm) {
		// ตรวจสอบว่ามีแถว lock ถูกลบไปหรือไม่
		if (frm.__locked_rows_backup && frm.__locked_rows_backup.length > 0) {
			// หา material_issue ที่ยังอยู่
			let current_material_issues = [];
			if (frm.doc.service_items) {
				for (let i = 0; i < frm.doc.service_items.length; i++) {
					if (frm.doc.service_items[i].material_issue) {
						current_material_issues.push(frm.doc.service_items[i].material_issue);
					}
				}
			}

			// หาแถวที่หายไป
			let deleted_locked_rows = [];
			for (let j = 0; j < frm.__locked_rows_backup.length; j++) {
				let backup = frm.__locked_rows_backup[j];
				if (
					backup.material_issue &&
					current_material_issues.indexOf(backup.material_issue) === -1
				) {
					deleted_locked_rows.push(backup);
				}
			}

			if (deleted_locked_rows.length > 0) {
				// มีแถวที่ lock ถูกลบ - ต้องหยุดการ save
				let item_names = [];
				for (let k = 0; k < deleted_locked_rows.length; k++) {
					item_names.push(
						deleted_locked_rows[k].item_name || deleted_locked_rows[k].item_code
					);
				}

				frappe.msgprint({
					title: __("ไม่สามารถบันทึกได้"),
					indicator: "red",
					message: __(
						'ไม่สามารถลบรายการ "{0}" ได้เพราะมีใบเบิกอะไหล่ที่ถูก submit แล้ว<br>กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบ<br><br>กำลัง reload เอกสาร...',
						[item_names.join(", ")]
					),
				});

				frappe.validated = false;

				// Reload document หลังจาก 1.5 วินาที
				setTimeout(function () {
					frm.reload_doc();
				}, 1500);

				return false;
			}
		}
	},

	before_submit: function (frm) {
		// ตรวจสอบ Material Issues ก่อน Submit
		// ถ้ามี flag ว่าตรวจสอบแล้ว (จากการสร้าง MI สำเร็จ) ให้ข้าม
		if (frm.__mi_checked) {
			frm.__mi_checked = false;
			return;
		}

		frappe.validated = false;

		frappe.call({
			method: "truck_service_center.truck_service_center.doctype.service_order.service_order.check_material_issues_before_submit",
			args: { service_order: frm.doc.name },
			async: false,
			callback: function (r) {
				if (!r.message) return;

				let result = r.message;

				if (result.can_submit) {
					// ผ่านการตรวจสอบ - อนุญาตให้ submit
					frappe.validated = true;
					return;
				}

				// จำนวนในใบสั่งงานไม่ตรงกับที่เบิกจริง หรือใบเบิกไม่มีบรรทัดที่ตรงกัน
				// (แก้เองไม่ได้ ต้องให้ผู้ใช้ไปจัดการก่อน)
				let mismatches = (result.qty_mismatches || []).map(function (row) {
					return (
						"• " + row.label + ": ใบสั่งงาน " + row.ordered + " / เบิกจริง " + row.issued
					);
				});
				let missing = (result.missing_lines || []).map(function (row) {
					return "• " + row.label + " → ไม่พบบรรทัดใน " + row.material_issue;
				});

				if (mismatches.length > 0 || missing.length > 0) {
					frappe.msgprint({
						title: __("ไม่สามารถ Submit ได้"),
						indicator: "red",
						message: __(
							"ใบเบิกอะไหล่ไม่ตรงกับรายการในใบสั่งงาน:<br>{0}<br><br>กรุณาแก้จำนวนให้ตรงกัน หรือยกเลิกใบเบิกแล้วเบิกใหม่",
							[mismatches.concat(missing).join("<br>")]
						),
					});
					return;
				}

				// มี Material Issues ที่ยังไม่ได้ submit
				if (Object.keys(result.unsubmitted_mis).length > 0) {
					let mi_list = Object.entries(result.unsubmitted_mis)
						.map(function (entry) {
							return "• " + entry[0] + " (สถานะ: " + entry[1] + ")";
						})
						.join("<br>");

					frappe.msgprint({
						title: __("ไม่สามารถ Submit ได้"),
						indicator: "red",
						message: __(
							"ใบเบิกอะไหล่ต่อไปนี้ยังไม่ได้ Submit:<br>{0}<br><br>กรุณา Submit ใบเบิกอะไหล่ทั้งหมดก่อน Submit Service Order",
							[mi_list]
						),
					});
					return;
				}

				// มี items ที่ยังไม่มี Material Issue - สอบถามว่าจะสร้างให้หรือไม่
				if (result.items_without_mi.length > 0) {
					let item_list = result.items_without_mi
						.map(function (item) {
							return "• " + item.item_name + " (แถวที่ " + item.idx + ")";
						})
						.join("<br>");

					frappe.confirm(
						__(
							"รายการอะไหล่ต่อไปนี้ยังไม่มีใบเบิกอะไหล่ (Material Issue):<br>{0}<br><br>ต้องการสร้างใบเบิกอะไหล่ให้อัตโนมัติหรือไม่?",
							[item_list]
						),
						function () {
							// ตอบตกลง - สร้าง Material Issue
							frappe.call({
								method: "truck_service_center.truck_service_center.doctype.service_order.service_order.create_material_issue",
								args: { service_order: frm.doc.name },
								callback: function (r) {
									if (r.message) {
										frappe.show_alert(
											{
												message: __(
													"สร้าง Material Issue {0} เรียบร้อยแล้ว<br>กรุณา Submit ใบเบิกอะไหล่ก่อน แล้วจึง Submit Service Order อีกครั้ง",
													[r.message]
												),
												indicator: "green",
											},
											7
										);
										frm.reload_doc();
									}
								},
							});
						},
						function () {
							// ตอบยกเลิก - ไม่ทำอะไร
							frappe.show_alert(
								{
									message: __(
										"กรุณาสร้างใบเบิกอะไหล่ (Material Issue) สำหรับรายการอะไหล่ทั้งหมดก่อน Submit"
									),
									indicator: "orange",
								},
								5
							);
						}
					);
					return;
				}
			},
		});
	},
});

// Event handlers สำหรับ child table แพ็คเกจบริการ
frappe.ui.form.on("Service Order Package", {
	service_package: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.service_package) return;

		frappe.call({
			method: "truck_service_center.truck_service_center.doctype.service_package.service_package.get_package_details",
			args: { package_name: row.service_package },
			callback: function (r) {
				if (!r.message) return;
				let pkg = r.message;
				let pkg_name = row.service_package;
				// ส่วนลดต่อบรรทัดเป็นบาทจาก server — รวมแล้วตรงราคาแพ็คเกจพอดี

				// เพิ่ม service types จาก package
				(pkg.service_types || []).forEach(function (st) {
					let st_row = frm.add_child("service_types");
					st_row.service_type = st.service_type;
					st_row.service_type_group = st.service_type_group;
					st_row.maintenance_type = st.maintenance_type;
					st_row.estimated_time = st.estimated_time;
					st_row.labor_charges = st.labor_rate;
					st_row.discount_amount = flt(st.discount_amount);
					st_row.discount_percentage = flt(st.discount_percentage);
					st_row.service_package = pkg_name;
				});

				// เพิ่ม parts จาก package
				(pkg.parts || []).forEach(function (part) {
					let item_row = frm.add_child("service_items");
					item_row.item_code = part.item_code;
					item_row.item_name = part.item_name;
					item_row.qty = part.qty;
					item_row.uom = part.uom;
					item_row.rate = part.rate;
					item_row.discount_amount = flt(part.discount_amount);
					item_row.discount_percentage = flt(part.discount_percentage);
					item_row.service_package = pkg_name;
					item_row.service_type = part.service_type;
				});

				frm.refresh_field("service_types");
				frm.refresh_field("service_items");
				calculate_totals(frm);

				frappe.show_alert({
					message: __('โหลดรายการจากแพ็คเกจ "{0}" เรียบร้อย', [
						pkg.package_name || pkg_name,
					]),
					indicator: "green",
				});
			},
		});
	},

	service_packages_remove: function (frm, cdt, cdn) {
		// Cascade delete: ลบ service_types และ service_items ที่ผูกกับ package ที่ถูกลบ
		let current_packages = new Set();
		(frm.doc.service_packages || []).forEach(function (pkg_row) {
			if (pkg_row.service_package) {
				current_packages.add(pkg_row.service_package);
			}
		});

		// หา service_types ที่ต้องลบ (ผูกกับ package ที่ไม่อยู่แล้ว)
		let new_service_types = (frm.doc.service_types || []).filter(function (st) {
			return !st.service_package || current_packages.has(st.service_package);
		});

		// หา service_items ที่ต้องลบ (ผูกกับ package ที่ไม่อยู่แล้ว แต่ต้องไม่มี material_issue)
		let new_service_items = (frm.doc.service_items || []).filter(function (si) {
			if (!si.service_package || current_packages.has(si.service_package)) {
				return true;
			}
			// ถ้ามี material_issue ที่ submitted แล้ว ไม่ลบ
			if (si.material_issue && si.material_issue_status === "Submitted") {
				return true;
			}
			return false;
		});

		frm.doc.service_types = new_service_types;
		frm.doc.service_items = new_service_items;

		// Re-index
		frm.doc.service_types.forEach(function (row, idx) {
			row.idx = idx + 1;
		});
		frm.doc.service_items.forEach(function (row, idx) {
			row.idx = idx + 1;
		});

		frm.refresh_field("service_types");
		frm.refresh_field("service_items");
		calculate_totals(frm);
	},
});

// Event handlers สำหรับ child table ประเภทบริการ
frappe.ui.form.on("Service Order Service Type", {
	service_types_add: function (frm) {
		calculate_totals(frm);
	},

	start_time: function (frm) {
		preview_actual_time(frm);
	},

	end_time: function (frm) {
		preview_actual_time(frm);
	},

	service_bay: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.service_bay || frm.is_new()) return;

		let row_bays = {};
		row_bays[row.name] = row.service_bay;
		confirm_bay_change(frm, { row_bays: JSON.stringify(row_bays) }, function () {
			frappe.model.set_value(cdt, cdn, "service_bay", null);
		});
	},

	// ห้ามลบประเภทบริการที่อะไหล่ของมันถูกเบิกไปแล้ว ไม่งั้นอะไหล่จะค้างเป็นแถวไร้ที่มา
	// (remove_orphan_service_type_items ไม่ลบแถวที่มีใบเบิก submit) ใบงานกับใบเบิกจะไม่ตรงกัน
	//
	// ต้อง "reject promise" เท่านั้นจึงจะบล็อกได้ — grid_row.remove() ร้อย before_*_remove
	// ไว้ใน frappe.run_serially แล้วดูแค่ว่า chain reject หรือไม่ การ return false ไม่มีผล
	before_service_types_remove: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.service_type) return;

		// ถ้ายังมีแถวอื่นใช้ service type เดียวกัน อะไหล่จะไม่ถูก cascade ลบ จึงลบแถวนี้ได้
		let still_used = (frm.doc.service_types || []).some(function (st) {
			return st.name !== row.name && st.service_type === row.service_type;
		});
		if (still_used) return;

		let issues = [];
		(frm.doc.service_items || []).forEach(function (si) {
			if (
				si.service_type === row.service_type &&
				si.material_issue &&
				si.material_issue_status === "Submitted" &&
				issues.indexOf(si.material_issue) === -1
			) {
				issues.push(si.material_issue);
			}
		});
		if (!issues.length) return;

		frappe.msgprint({
			title: __("ไม่สามารถลบประเภทบริการได้"),
			indicator: "red",
			message: __(
				'อะไหล่ของ "{0}" ถูกเบิกไปแล้วตามใบเบิก {1}<br>กรุณายกเลิกใบเบิกอะไหล่ก่อน จึงจะลบประเภทบริการนี้ได้',
				[
					row.service_type,
					issues
						.map(function (name) {
							return `<a href="/app/stock-entry/${name}" target="_blank">${name}</a>`;
						})
						.join(", "),
				]
			),
		});

		return Promise.reject(new Error("service type has submitted material issue"));
	},

	service_types_remove: function (frm) {
		// Cascade delete แบบเดียวกับตอนลบแพ็คเกจ — อะไหล่ที่ดึงมาจาก service type
		// ที่ถูกลบไม่ควรค้างอยู่ในใบงาน
		remove_orphan_service_type_items(frm);
		calculate_totals(frm);
	},

	service_type: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.service_type) return;

		// ใช้ตัวเดียวกับตอนสแกนบาร์โค้ด เพื่อให้ถามยืนยันและ stamp ที่มาเหมือนกัน
		check_and_add_service_type_items(frm, row.service_type);
	},

	labor_charges: function (frm, cdt, cdn) {
		// เมื่อเปลี่ยน labor_charges → คำนวณส่วนลดใหม่
		calculate_service_type_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	discount_percentage: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		// คิดบาทใหม่เฉพาะเมื่อ % ไม่ตรงกับบาทเดิม — ถ้าตรงอยู่แล้วแปลว่า % ถูกตั้งจากช่องบาท ห้ามคิดกลับ
		if (!flt(row.discount_percentage)) {
			if (flt(row.labor_charges) > 0) frappe.model.set_value(cdt, cdn, "discount_amount", 0);
		} else {
			let values = resolve_line_discount(row.labor_charges, row.discount_percentage, row.discount_amount);
			if (values.discount_amount !== flt(row.discount_amount)) {
				frappe.model.set_value(cdt, cdn, "discount_amount", values.discount_amount);
			}
		}
		calculate_service_type_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	discount_amount: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		// บาทคือค่าที่ผู้ใช้คีย์ — % แค่ตามให้ตรง
		let pct = discount_percent_of(row.discount_amount, row.labor_charges);
		if (pct !== flt(row.discount_percentage, 2)) {
			frappe.model.set_value(cdt, cdn, "discount_percentage", pct);
		}
		calculate_service_type_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	estimated_time: function (frm, cdt, cdn) {
		calculate_totals(frm);
	},
});

frappe.ui.form.on("Service Order Item", {
	service_items_add: function (frm) {
		calculate_totals(frm);
	},

	service_items_remove: function (frm, cdt, cdn) {
		console.log("=== service_items_remove called ===");
		console.log("frm.__locked_rows_backup:", frm.__locked_rows_backup);
		console.log("frm.doc.service_items:", frm.doc.service_items);

		// ตรวจสอบว่ามีแถว lock ถูกลบไปหรือไม่
		if (frm.__locked_rows_backup && frm.__locked_rows_backup.length > 0) {
			// หา material_issue ที่ยังอยู่
			let current_material_issues = [];
			if (frm.doc.service_items) {
				for (let i = 0; i < frm.doc.service_items.length; i++) {
					if (frm.doc.service_items[i].material_issue) {
						current_material_issues.push(frm.doc.service_items[i].material_issue);
					}
				}
			}

			console.log("current_material_issues:", current_material_issues);

			// หาแถวที่หายไป
			let missing_rows = [];
			for (let j = 0; j < frm.__locked_rows_backup.length; j++) {
				let backup = frm.__locked_rows_backup[j];
				console.log(
					"checking backup:",
					backup.material_issue,
					"exists:",
					current_material_issues.indexOf(backup.material_issue)
				);
				if (
					backup.material_issue &&
					current_material_issues.indexOf(backup.material_issue) === -1
				) {
					missing_rows.push(backup);
				}
			}

			console.log("missing_rows:", missing_rows);

			if (missing_rows.length > 0) {
				// แสดงข้อความเตือน
				let item_names = [];
				for (let k = 0; k < missing_rows.length; k++) {
					item_names.push(missing_rows[k].item_name || missing_rows[k].item_code);
				}

				frappe.msgprint({
					title: __("ไม่สามารถลบได้"),
					indicator: "red",
					message: __(
						'ไม่สามารถลบรายการ "{0}" ได้เพราะมีใบเบิกอะไหล่ที่ถูก submit แล้ว<br>กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบ<br><br>กำลังคืนค่า...',
						[item_names.join(", ")]
					),
				});

				console.log("Calling frm.reload_doc()");
				// Reload document เพื่อคืนค่า
				frm.reload_doc();
				return;
			}
		} else {
			console.log("No locked_rows_backup found");
		}

		calculate_totals(frm);
	},

	// ป้องกันการแก้ไขเมื่อมี Material Issue ที่ submit แล้ว
	before_service_items_remove: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.__is_locked) {
			frappe.msgprint({
				title: __("ไม่สามารถลบได้"),
				indicator: "red",
				message: __(
					"ไม่สามารถลบแถวนี้ได้เพราะใบเบิกอะไหล่ {0} ถูก submit แล้ว กรุณายกเลิกใบเบิกอะไหล่ก่อน",
					[
						'<a href="/app/stock-entry/' +
							row.material_issue +
							'" target="_blank">' +
							row.material_issue +
							"</a>",
					]
				),
			});
			frappe.validated = false;
			return false;
		}
	},

	// ป้องกันการแก้ไขทุก field ก่อนเข้า edit mode
	form_render: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		let is_locked =
			row.__is_locked || (row.material_issue && row.material_issue_status === "Submitted");

		if (is_locked) {
			// ทำให้แก้ไขไม่ได้เลย
			lock_specific_row(frm, cdn);

			// ซ่อน row-action (มีปุ่ม Delete)
			setTimeout(function () {
				let grid_row = frm.fields_dict.service_items.grid.grid_rows_by_docname[cdn];
				if (grid_row && grid_row.grid_form) {
					$(grid_row.grid_form.wrapper).find(".row-actions").hide();
				}
			}, 50);
		}
	},

	item_code: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];

		// ป้องกันการแก้ไขถ้าแถวถูกล็อค (Material Issue ที่ submit แล้ว)
		if (row.__is_locked) {
			frappe.show_alert({
				message: __("ไม่สามารถแก้ไขได้เพราะใบเบิกอะไหล่ {0} ถูก submit แล้ว", [
					row.material_issue,
				]),
				indicator: "red",
			});
			// คืนค่าเดิมที่บันทึกไว้
			if (row.__locked_old_item_code !== undefined) {
				frappe.model.set_value(cdt, cdn, "item_code", row.__locked_old_item_code);
			}
			return;
		}

		if (row.item_code) {
			// ดึงข้อมูล Item และราคาจาก Item Price
			frappe.call({
				method: "truck_service_center.truck_service_center.doctype.service_order.service_order.get_item_rate",
				args: {
					item_code: row.item_code,
					customer: frm.doc.customer,
				},
				callback: function (r) {
					if (r.message) {
						frappe.model.set_value(cdt, cdn, "item_name", r.message.item_name);
						frappe.model.set_value(cdt, cdn, "description", r.message.description);
						frappe.model.set_value(cdt, cdn, "uom", r.message.uom);
						frappe.model.set_value(cdt, cdn, "rate", r.message.rate || 0);

						// สรุปยอดทันทีที่เลือกอะไหล่ ไม่ต้องรอ trigger ของ rate
						// (frappe.model.set_value จะไม่ยิง trigger ถ้าค่าใหม่เท่าค่าเดิม
						// เช่น เปลี่ยนไปอะไหล่ที่ราคาเท่ากัน หรือราคาเป็น 0 ทั้งคู่)
						calculate_item_amount(frm, cdt, cdn);
						calculate_totals(frm);

						// แสดงข้อความถ้าราคาเป็น 0
						if (!r.message.rate || r.message.rate === 0) {
							frappe.show_alert({
								message: __(
									"No price found for this item. Please set Item Price or Standard Rate."
								),
								indicator: "orange",
							});
						}
					}
				},
			});
		}
	},

	qty: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];

		// ป้องกันการแก้ไขถ้าแถวถูกล็อค (Material Issue ที่ submit แล้ว)
		if (row.__is_locked) {
			frappe.show_alert({
				message: __("ไม่สามารถแก้ไขจำนวนได้เพราะใบเบิกอะไหล่ {0} ถูก submit แล้ว", [
					row.material_issue,
				]),
				indicator: "red",
			});
			// คืนค่าเดิมที่บันทึกไว้
			if (row.__locked_old_qty !== undefined) {
				frappe.model.set_value(cdt, cdn, "qty", row.__locked_old_qty);
			}
			return;
		}

		calculate_item_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	rate: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];

		// ป้องกันการแก้ไขถ้าแถวถูกล็อค (Material Issue ที่ submit แล้ว)
		if (row.__is_locked) {
			frappe.show_alert({
				message: __("ไม่สามารถแก้ไขราคาได้เพราะใบเบิกอะไหล่ {0} ถูก submit แล้ว", [
					row.material_issue,
				]),
				indicator: "red",
			});
			// คืนค่าเดิมที่บันทึกไว้
			if (row.__locked_old_rate !== undefined) {
				frappe.model.set_value(cdt, cdn, "rate", row.__locked_old_rate);
			}
			return;
		}

		calculate_item_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	discount_percentage: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		// คิดบาทใหม่เฉพาะเมื่อ % ไม่ตรงกับบาทเดิม — ถ้าตรงอยู่แล้วแปลว่า % ถูกตั้งจากช่องบาท ห้ามคิดกลับ
		if (!flt(row.discount_percentage)) {
			if (flt(row.rate) > 0) frappe.model.set_value(cdt, cdn, "discount_amount", 0);
		} else {
			let values = resolve_line_discount(row.rate, row.discount_percentage, row.discount_amount);
			if (values.discount_amount !== flt(row.discount_amount)) {
				frappe.model.set_value(cdt, cdn, "discount_amount", values.discount_amount);
			}
		}
		calculate_item_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	discount_amount: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		// บาทคือค่าที่ผู้ใช้คีย์ — % แค่ตามให้ตรง
		let pct = discount_percent_of(row.discount_amount, row.rate);
		if (pct !== flt(row.discount_percentage, 2)) {
			frappe.model.set_value(cdt, cdn, "discount_percentage", pct);
		}
		calculate_item_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},

	material_issue: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];

		// ถ้ามี Material Issue ให้ดึงสถานะล่าสุด
		if (row.material_issue) {
			frappe.db.get_value("Stock Entry", row.material_issue, "docstatus", function (r) {
				if (r && r.docstatus !== undefined) {
					let status_map = { 0: "Draft", 1: "Submitted", 2: "Cancelled" };
					frappe.model.set_value(
						cdt,
						cdn,
						"material_issue_status",
						status_map[r.docstatus]
					);

					// ถ้า Material Issue เป็น Submitted แล้ว ให้ล็อคแถวนี้
					if (r.docstatus === 1) {
						// รอให้ field update เสร็จก่อน
						setTimeout(function () {
							lock_rows_with_submitted_material_issue(frm);
						}, 100);
					}
				}
			});
		} else {
			// ถ้าไม่มี Material Issue ให้ล้างสถานะ
			frappe.model.set_value(cdt, cdn, "material_issue_status", null);
		}
	},
});

function calculate_item_amount(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let values = get_item_amounts(row);
	set_row_value(row, "discount_amount", values.discount_amount);
	set_row_value(row, "amount", values.amount);
}

// ปกติ Frappe จะคำนวณให้ตอน "ออกจากช่อง" (event change) เท่านั้น
// สองฟังก์ชันนี้ทำให้ยอดในแถวและยอดรวมท้ายเอกสารขยับตั้งแต่ตอนพิมพ์
function setup_live_row_calc(frm) {
	bind_live_row_calc(frm, "service_items", ["qty", "rate"], calculate_item_amount);
	bind_live_row_calc(
		frm,
		"service_types",
		["labor_charges", "estimated_time"],
		calculate_service_type_amount
	);
}

function bind_live_row_calc(frm, gridfield, fieldnames, recalc_row) {
	let field = frm.fields_dict[gridfield];
	if (!field || !field.grid || field.grid.__live_row_calc) return;

	let grid = field.grid;
	grid.__live_row_calc = true;

	grid.wrapper.on("input", "input[data-fieldname]", function () {
		let fieldname = $(this).attr("data-fieldname");
		if (fieldnames.indexOf(fieldname) === -1) return;

		let cdt = grid.doctype;
		let cdn = $(this).closest(".grid-row").attr("data-name");
		let row = cdn && locals[cdt] && locals[cdt][cdn];
		if (!row || row.__is_locked) return;

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

// mirror ของ truck_service_center/discounts.py (ต้องแก้คู่กัน) — ส่วนลดบาทเป็นตัวหลัก % เป็นค่าที่คำนวณไว้แสดง
// % ปัด 2 ตำแหน่ง ถ้าคิดบาทกลับจาก % ทุกครั้งจะได้เศษ (300 ลด 100 → 33.33% → 99.99 → ยอด 200.01)
function discount_percent_of(amount, base) {
	return flt(base) > 0 ? flt((flt(amount) / flt(base)) * 100, 2) : 0;
}

// คิดบาทจาก % เฉพาะเมื่อ % ไม่ตรงกับบาทที่มีอยู่ (ผู้ใช้เพิ่งแก้ % หรือราคาฐานเปลี่ยน ซึ่งคง % ไว้)
function resolve_line_discount(base, discount_percentage, discount_amount) {
	base = flt(base);
	let pct = flt(discount_percentage);
	let amount = flt(discount_amount, 2);
	if (base <= 0) return { discount_percentage: pct, discount_amount: amount };

	if (pct && discount_percent_of(amount, base) !== flt(pct, 2)) {
		amount = flt((base * pct) / 100, 2);
	}
	return { discount_percentage: discount_percent_of(amount, base), discount_amount: amount };
}

// คำนวณส่วนลดระดับบรรทัดสำหรับ Service Order Item — คืนค่าใหม่โดยไม่แก้ค่าใน item
function get_item_amounts(item) {
	let rate = flt(item.rate);
	let qty = flt(item.qty);
	let values = resolve_line_discount(rate, item.discount_percentage, item.discount_amount);

	let net_rate = flt(rate - values.discount_amount, 2);
	if (net_rate < 0) net_rate = 0;

	return {
		discount_percentage: values.discount_percentage,
		discount_amount: values.discount_amount,
		amount: flt(net_rate * qty, 2),
	};
}

function calculate_service_type_amount(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let values = get_service_type_amounts(row);
	set_row_value(row, "discount_amount", values.discount_amount);
	set_row_value(row, "amount", values.amount);
}

// คำนวณส่วนลดระดับบรรทัดสำหรับ Service Order Service Type — คืนค่าใหม่โดยไม่แก้ค่าใน row
function get_service_type_amounts(row) {
	let labor = flt(row.labor_charges);
	let values = resolve_line_discount(labor, row.discount_percentage, row.discount_amount);

	// amount = labor_charges หลังส่วนลด
	let net_labor = flt(labor - values.discount_amount, 2);
	if (net_labor < 0) net_labor = 0;

	return {
		discount_percentage: values.discount_percentage,
		discount_amount: values.discount_amount,
		amount: flt(net_labor, 2),
	};
}

// ฟังก์ชันตรวจสอบและเพิ่มรายการอะไหล่จาก Service Type
function check_and_add_service_type_items(frm, service_type) {
	frappe.call({
		method: "truck_service_center.truck_service_center.doctype.service_order.service_order.get_service_type_items",
		args: {
			service_type: service_type,
		},
		callback: function (r) {
			if (r.message && r.message.length > 0) {
				let items = r.message;
				let item_list = items
					.map(
						(item) =>
							`• ${item.item_name || item.item_code} - จำนวน: ${item.qty} ${
								item.uom || ""
							} (฿${item.rate || 0})`
					)
					.join("<br>");

				frappe.confirm(
					__(
						'ประเภทบริการ "{0}" มีรายการอะไหล่มาตรฐาน {1} รายการ:<br><br>{2}<br><br>ต้องการเพิ่มรายการอะไหล่เหล่านี้ในใบสั่งงานหรือไม่?',
						[service_type, items.length, item_list]
					),
					function () {
						// Yes - เพิ่มรายการอะไหล่
						add_service_type_items_to_order(frm, items, service_type);
					},
					function () {
						// No - ไม่ต้องทำอะไร
					}
				);
			}
		},
	});
}

// ฟังก์ชันเพิ่มรายการอะไหล่จาก Service Type
function add_service_type_items_to_order(frm, items, service_type) {
	// สร้างแถวใหม่เสมอ ไม่รวม qty เข้าแถวเดิม เพื่อให้อะไหล่ทุกแถวมีที่มาเพียง
	// service type เดียว — ถ้ารวมแถว จะบอกไม่ได้ว่าต้องลบเท่าไหร่ตอนลบ service type
	items.forEach(function (item) {
		let new_row = frm.add_child("service_items");
		new_row.item_code = item.item_code;
		new_row.item_name = item.item_name;
		new_row.description = item.description;
		new_row.qty = item.qty;
		new_row.uom = item.uom;
		new_row.rate = item.rate;
		new_row.amount = item.amount || item.qty * item.rate;
		new_row.service_type = service_type;
	});

	frm.refresh_field("service_items");
	calculate_totals(frm);

	frappe.show_alert({
		message: __('เพิ่มรายการอะไหล่ {0} รายการจาก "{1}" เรียบร้อย', [
			items.length,
			service_type,
		]),
		indicator: "green",
	});
}

/**
 * ลบอะไหล่ที่ดึงมาจาก service type ซึ่งไม่อยู่ในตารางประเภทบริการแล้ว
 * เก็บไว้: อะไหล่ที่เพิ่มเอง (service_type ว่าง) และแถวที่มีใบเบิกซึ่ง submit แล้ว
 */
function remove_orphan_service_type_items(frm) {
	let remaining = new Set();
	(frm.doc.service_types || []).forEach(function (st) {
		if (st.service_type) {
			remaining.add(st.service_type);
		}
	});

	frm.doc.service_items = (frm.doc.service_items || []).filter(function (si) {
		if (!si.service_type || remaining.has(si.service_type)) {
			return true;
		}
		// ใบเบิกที่ submit แล้วลบไม่ได้ ต้องยกเลิกใบเบิกก่อน
		return si.material_issue && si.material_issue_status === "Submitted";
	});

	frm.doc.service_items.forEach(function (row, idx) {
		row.idx = idx + 1;
	});
	frm.refresh_field("service_items");
}

const TECHNICIAN_FIELDS = [
	"technician",
	"technician_2",
	"technician_3",
	"technician_4",
	"technician_5",
	"technician_6",
	"technician_7",
	"technician_8",
	"technician_9",
	"technician_10",
];

// ช่องช่างของแถวงาน (Service Order Service Type) — แบน 10 ช่องเหมือนกัน
const ROW_TECHNICIAN_FIELDS = [
	"technician_1",
	"technician_2",
	"technician_3",
	"technician_4",
	"technician_5",
	"technician_6",
	"technician_7",
	"technician_8",
	"technician_9",
	"technician_10",
];

function set_technician_filter(frm) {
	// ตั้งค่า filter สำหรับช่างผู้รับผิดชอบ ให้แสดงเฉพาะผู้ใช้ที่มีบทบาท Technician
	TECHNICIAN_FIELDS.forEach(function (fieldname) {
		frm.set_query(fieldname, function () {
			return {
				query: "truck_service_center.queries.technician_query",
			};
		});
	});

	// ช่องช่างในกริดงานใช้ filter ชุดเดียวกัน จะได้ไม่ขึ้น user ทุกคนในระบบ
	ROW_TECHNICIAN_FIELDS.forEach(function (fieldname) {
		frm.set_query(fieldname, "service_types", function () {
			return {
				query: "truck_service_center.queries.technician_query",
			};
		});
	});
}

function set_bay_filter(frm) {
	// เลือกได้เฉพาะช่องจอดที่ยังเปิดใช้งาน ทั้งช่องจอดหลักและช่องจอดรายแถว
	frm.set_query("service_bay", function () {
		return { filters: { is_active: 1 } };
	});
	frm.set_query("service_bay", "service_types", function () {
		return { filters: { is_active: 1 } };
	});
}

// เตือนเรื่องช่องจอดก่อนตั้งค่าจริง — ยกเลิกแล้วคืนค่าเดิม (เตือนอย่างเดียว ไม่ห้าม)
function confirm_bay_change(frm, args, on_cancel) {
	frappe.call({
		method: "truck_service_center.truck_service_center.doctype.service_order.service_order.check_bay_conflicts",
		args: Object.assign({ service_order: frm.doc.name }, args),
		callback: function (r) {
			let warnings = (r && r.message && r.message.warnings) || [];
			if (!warnings.length) return;

			frappe.confirm(
				warnings.join("<br>") + "<br><br>" + __("ยืนยันใช้ช่องจอดนี้?"),
				function () {},
				on_cancel
			);
		},
	});
}

// เติมช่องจอดหลักลงแถวที่ยังว่าง — mirror ของ apply_default_bay ฝั่ง server
// ทำฝั่ง client ด้วยเพื่อให้เห็นผลทันทีโดยไม่ต้องรอ save
function fill_empty_row_bays(frm) {
	if (!frm.doc.service_bay) return;

	let changed = false;
	(frm.doc.service_types || []).forEach(function (row) {
		if (!row.service_bay) {
			row.service_bay = frm.doc.service_bay;
			changed = true;
		}
	});

	if (changed) frm.refresh_field("service_types");
}

function set_vehicle_filter(frm) {
	// ตั้งค่า filter สำหรับ Vehicle ให้แสดงเฉพาะรถของลูกค้าที่เลือก
	if (frm.doc.customer) {
		frm.set_query("vehicle", function () {
			return {
				filters: {
					customer: frm.doc.customer,
					status: "Active",
				},
			};
		});
	} else {
		// ถ้ายังไม่ได้เลือกลูกค้า ให้แสดงเฉพาะรถที่ Active
		frm.set_query("vehicle", function () {
			return {
				filters: {
					status: "Active",
				},
			};
		});
	}
}

// คำนวณยอดรวมทั้งหมด
function calculate_totals(frm) {
	// คำนวณค่าแรงรวมและเวลาประมาณการรวม (หลังส่วนลดระดับบรรทัด)
	let total_labor = 0;
	let total_time = 0;

	if (frm.doc.service_types) {
		frm.doc.service_types.forEach(function (row) {
			let values = get_service_type_amounts(row);
			// เขียนผ่าน model เพื่อให้ช่อง "ยอดรวม" ของแถวนั้นอัปเดตทันที
			set_row_value(row, "amount", values.amount);
			total_labor += flt(values.amount);
			total_time += flt(row.estimated_time);
		});
	}

	// อัพเดทค่าแรงและเวลารวม
	frm.set_value("labor_charges", total_labor);
	frm.set_value("estimated_time", total_time);

	// คำนวณยอดรวมอะไหล่ (หลังส่วนลดระดับบรรทัด)
	let total_parts = 0;
	if (frm.doc.service_items) {
		frm.doc.service_items.forEach(function (item) {
			let values = get_item_amounts(item);
			// เขียนผ่าน model เพื่อให้ช่อง "ยอดรวม" ของแถวนั้นอัปเดตทันที
			set_row_value(item, "amount", values.amount);
			total_parts += flt(values.amount);
		});
	}
	frm.set_value("total_parts_amount", total_parts);

	// คำนวณยอดก่อนภาษี (subtotal หลังหักส่วนลด)
	let subtotal = total_parts + total_labor - flt(frm.doc.discount_amount);

	// คำนวณภาษีตามประเภท
	let tax_type = frm.doc.tax_type;
	let vat_rate = flt(frm.doc.vat_rate);
	let net_total = 0;
	let tax_amount = 0;
	let total = 0;

	if (tax_type === "ราคารวม VAT" && vat_rate) {
		// ราคารวม VAT แล้ว → แยก VAT ออกจากยอดรวม
		tax_amount = flt((subtotal * vat_rate) / (100 + vat_rate), 2);
		net_total = flt(subtotal - tax_amount, 2);
		total = flt(subtotal, 2);
	} else if (tax_type === "ราคาแยก VAT" && vat_rate) {
		// ราคาแยก VAT → คิด VAT เพิ่มจากยอดสุทธิ
		net_total = flt(subtotal, 2);
		tax_amount = flt((subtotal * vat_rate) / 100, 2);
		total = flt(net_total + tax_amount, 2);
	} else {
		// ไม่คิด VAT
		net_total = flt(subtotal, 2);
		tax_amount = 0;
		total = flt(subtotal, 2);
	}

	frm.set_value("net_total", net_total);
	frm.set_value("tax_amount", tax_amount);
	frm.set_value("total_amount", total);

	// คำนวณยอดคงค้าง
	let outstanding = total - flt(frm.doc.paid_amount);
	frm.set_value("outstanding_amount", outstanding);

	// คำนวณภาษีหัก ณ ที่จ่าย (mirror ของ calculate_wht ฝั่ง server)
	calculate_wht(frm, total_labor, total_parts, total);
}

function calculate_wht(frm, total_labor, total_parts, total) {
	if (!frm.doc.apply_wht) {
		frm.set_value("wht_amount", 0);
		frm.set_value("net_payment_amount", total);
		return;
	}

	let gross = total_labor + total_parts;
	let subtotal = gross - flt(frm.doc.discount_amount);
	let base;

	if (frm.doc.wht_base === "ทั้งใบ (ค่าแรง+อะไหล่)") {
		base = subtotal;
	} else {
		base = gross ? (subtotal * total_labor) / gross : 0;
	}

	if (frm.doc.tax_type === "ราคารวม VAT" && flt(frm.doc.vat_rate)) {
		base = (base * 100) / (100 + flt(frm.doc.vat_rate));
	}

	let wht_rate = flt(frm.doc.wht_rate) || 3;
	let wht_amount = flt((base * wht_rate) / 100, 2);
	frm.set_value("wht_amount", wht_amount);
	frm.set_value("net_payment_amount", flt(total - wht_amount, 2));
}

function setup_service_package_filter(frm) {
	frm.set_query("service_package", "service_packages", function () {
		return {
			filters: {
				is_active: 1,
			},
		};
	});
}

function setup_service_type_filter(frm) {
	// ตั้งค่า filter สำหรับ service_type ใน child table service_types
	frm.set_query("service_type", "service_types", function (doc, cdt, cdn) {
		let row = locals[cdt][cdn];
		let filters = {
			is_active: 1,
		};

		// ถ้ามีการเลือก service_type_group ให้ filter ตาม group
		if (row.service_type_group) {
			filters["service_type_group"] = row.service_type_group;
		}

		return {
			filters: filters,
		};
	});
}

function show_material_issue_summary(frm) {
	// ถ้าเป็น document ใหม่ ให้ล้าง HTML และออก
	if (!frm.doc.name || frm.doc.__islocal) {
		if (
			frm.fields_dict.material_issue_summary &&
			frm.fields_dict.material_issue_summary.$wrapper
		) {
			frm.fields_dict.material_issue_summary.$wrapper.html("");
		}
		return;
	}

	frappe.call({
		method: "truck_service_center.truck_service_center.doctype.service_order.service_order.get_material_issue_summary",
		args: {
			service_order: frm.doc.name,
		},
		callback: function (r) {
			if (r.message) {
				let summary = r.message;
				let html = "";

				if (summary.total_count > 0) {
					html = '<div class="row">';
					html +=
						'<div class="col-12"><h5>Material Issues (' +
						summary.total_count +
						")</h5></div>";

					summary.material_issues.forEach(function (issue) {
						let badge_class =
							issue.status === "Submitted"
								? "success"
								: issue.status === "Draft"
								? "warning"
								: "danger";

						html += '<div class="col-md-6 col-12" style="margin-bottom: 10px;">';
						html +=
							'<div class="card" style="border-left: 3px solid var(--bs-' +
							badge_class +
							');">';
						html += '<div class="card-body" style="padding: 10px;">';
						html +=
							'<a href="/app/stock-entry/' +
							issue.name +
							'" target="_blank"><strong>' +
							issue.name +
							"</strong></a>";
						html +=
							'<span class="badge badge-' +
							badge_class +
							'" style="float: right;">' +
							issue.status +
							"</span>";
						html +=
							"<br><small>" +
							issue.posting_date +
							" | Items: " +
							issue.item_count +
							"</small>";

						// ใบเบิก Draft ยังแก้ได้ทั้งสองฝั่ง จึงต้องให้ผู้ใช้เลือกทิศทางเอง
						if (issue.status === "Draft") {
							html += '<br><div class="btn-group" style="margin-top: 5px;">';
							html +=
								'<button class="btn btn-xs btn-default" title="เอาจำนวนในใบเบิกมาทับใบสั่งงาน" ' +
								"onclick=\"sync_material_issue('" +
								frm.doc.name +
								"', '" +
								issue.name +
								"')\">";
							html += '<i class="fa fa-arrow-left"></i> ดึงจากใบเบิก</button>';
							html +=
								'<button class="btn btn-xs btn-default" title="แก้ใบเบิกให้ตรงกับใบสั่งงาน" ' +
								"onclick=\"push_to_material_issue('" +
								frm.doc.name +
								"', '" +
								issue.name +
								"')\">";
							html += 'ส่งไปใบเบิก <i class="fa fa-arrow-right"></i></button>';
							html += "</div>";
						}

						html += "</div></div></div>";
					});

					html += "</div>";
				} else {
					html = '<p class="text-muted">ยังไม่มี Material Issue</p>';
				}

				frm.fields_dict.material_issue_summary.$wrapper.html(html);
			}
		},
	});
}

function create_material_issue_dialog(frm) {
	// แสดง dialog เพื่อให้เลือก items ที่จะสร้าง Material Issue
	let unlinked_items = [];

	frm.doc.service_items.forEach(function (item, idx) {
		if (!item.material_issue && item.item_code) {
			unlinked_items.push({
				idx: idx,
				item_code: item.item_code,
				item_name: item.item_name,
				qty: item.qty,
				warehouse: item.warehouse,
			});
		}
	});

	if (unlinked_items.length === 0) {
		frappe.msgprint(__("All items are already linked to Material Issues"));
		return;
	}

	// สร้าง Material Issue สำหรับทุก item ที่ยังไม่ link
	frappe.call({
		method: "truck_service_center.truck_service_center.doctype.service_order.service_order.create_material_issue",
		args: {
			service_order: frm.doc.name,
		},
		callback: function (r) {
			if (r.message) {
				frappe.show_alert({
					message: __("Material Issue {0} created", [r.message]),
					indicator: "green",
				});
				// Reload เพื่อ update สถานะ Material Issue
				frm.reload_doc();
			}
		},
	});
}

window.sync_material_issue = function (service_order, material_issue) {
	frappe.call({
		method: "truck_service_center.truck_service_center.doctype.service_order.service_order.sync_material_issue",
		args: {
			service_order: service_order,
			material_issue: material_issue,
		},
		callback: function (r) {
			if (r.message) {
				// Reload เพื่อ update สถานะ Material Issue
				cur_frm.reload_doc();
			}
		},
	});
};

// ทิศทางตรงข้าม: แก้ใบเบิก Draft ให้ตรงกับใบสั่งงาน
window.push_to_material_issue = function (service_order, material_issue) {
	frappe.call({
		method: "truck_service_center.truck_service_center.doctype.service_order.service_order.push_to_material_issue",
		args: {
			service_order: service_order,
			material_issue: material_issue,
		},
		callback: function (r) {
			if (r.message) {
				cur_frm.reload_doc();
			}
		},
	});
};

// Update สถานะ Material Issue ทั้งหมดจาก database
function update_material_issue_statuses(frm) {
	if (!frm.doc.service_items || frm.doc.__islocal) return;

	// รวบรวม Material Issue ที่ต้องตรวจสอบ
	let material_issues = [];
	frm.doc.service_items.forEach(function (item) {
		if (item.material_issue && !material_issues.includes(item.material_issue)) {
			material_issues.push(item.material_issue);
		}
	});

	if (material_issues.length === 0) return;

	// ดึงสถานะจาก database
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Stock Entry",
			filters: {
				name: ["in", material_issues],
			},
			fields: ["name", "docstatus"],
		},
		callback: function (r) {
			if (r.message) {
				// สร้าง map ของสถานะ
				let status_map = {};
				r.message.forEach(function (entry) {
					if (entry.docstatus === 0) {
						status_map[entry.name] = "Draft";
					} else if (entry.docstatus === 1) {
						status_map[entry.name] = "Submitted";
					} else if (entry.docstatus === 2) {
						status_map[entry.name] = "Cancelled";
					}
				});

				// Update สถานะในแต่ละแถว
				let updated = false;
				frm.doc.service_items.forEach(function (item) {
					if (item.material_issue && status_map[item.material_issue]) {
						if (item.material_issue_status !== status_map[item.material_issue]) {
							item.material_issue_status = status_map[item.material_issue];
							updated = true;
						}
					}
				});

				// Refresh grid ถ้ามีการเปลี่ยนแปลง
				if (updated) {
					frm.refresh_field("service_items");
					// เรียก lock_rows อีกครั้งหลังจาก update status
					setTimeout(function () {
						lock_rows_with_submitted_material_issue(frm);
					}, 100);
				}
			}
		},
	});
}

// ล็อค field เฉพาะของแถวที่ระบุ
function lock_specific_row(frm, cdn) {
	let grid_row = frm.fields_dict.service_items.grid.grid_rows_by_docname[cdn];
	if (!grid_row) return;

	let row = grid_row.doc;
	if (row.material_issue && row.material_issue_status === "Submitted") {
		// บันทึกค่าเดิมไว้เฉพาะเมื่อล็อค
		row.__locked_old_item_code = row.item_code;
		row.__locked_old_qty = row.qty;
		row.__locked_old_rate = row.rate;
		row.__locked_old_warehouse = row.warehouse;
		row.__is_locked = true;

		// เพิ่มสไตล์เพื่อแสดงว่าแถวนี้ถูกล็อค
		if (grid_row.wrapper) {
			grid_row.wrapper.addClass("locked-row");
			grid_row.wrapper.css("background-color", "#f5f5f5");
		}
	}
}

// ซ่อนปุ่มลบใน edit form สำหรับแถวที่ lock - ไม่ใช้แล้ว ใช้วิธี restore แทน
function hide_delete_button_in_form(frm) {
	// ไม่ทำอะไร - ใช้วิธี restore row แทนการซ่อนปุ่ม
}

// เก็บข้อมูลแถวที่ lock ไว้สำหรับ restore
function save_locked_rows_backup(frm) {
	if (!frm.doc.service_items) {
		frm.__locked_rows_backup = [];
		return;
	}

	frm.__locked_rows_backup = [];
	frm.doc.service_items.forEach(function (item) {
		if (
			item.__is_locked ||
			(item.material_issue && item.material_issue_status === "Submitted")
		) {
			// เก็บ copy ของข้อมูลแถวที่ lock
			frm.__locked_rows_backup.push({
				material_issue: item.material_issue,
				item_code: item.item_code,
				item_name: item.item_name,
				description: item.description,
				qty: item.qty,
				uom: item.uom,
				rate: item.rate,
				amount: item.amount,
				warehouse: item.warehouse,
				material_issue_status: item.material_issue_status,
				expense_account: item.expense_account,
				cost_center: item.cost_center,
				idx: item.idx,
			});
		}
	});
}

// คืนค่าแถวที่ lock ถ้าถูกลบไป
function restore_deleted_locked_rows(frm) {
	if (!frm.__locked_rows_backup || frm.__locked_rows_backup.length === 0) {
		return;
	}

	// หา material_issue ที่ยังอยู่
	let current_material_issues = [];
	if (frm.doc.service_items) {
		frm.doc.service_items.forEach(function (item) {
			if (item.material_issue) {
				current_material_issues.push(item.material_issue);
			}
		});
	}

	// หาแถวที่หายไป
	let missing_rows = [];
	frm.__locked_rows_backup.forEach(function (backup) {
		if (
			backup.material_issue &&
			current_material_issues.indexOf(backup.material_issue) === -1
		) {
			missing_rows.push(backup);
		}
	});

	if (missing_rows.length > 0) {
		// แสดงข้อความเตือน
		let item_names = missing_rows
			.map(function (r) {
				return r.item_name || r.item_code;
			})
			.join(", ");

		frappe.msgprint({
			title: __("ไม่สามารถลบได้"),
			indicator: "red",
			message: __(
				'ไม่สามารถลบรายการ "{0}" ได้เพราะมีใบเบิกอะไหล่ที่ถูก submit แล้ว<br>กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบ',
				[item_names]
			),
		});

		// คืนค่าแถวที่ถูกลบกลับมา
		missing_rows.forEach(function (backup) {
			let new_row = frm.add_child("service_items");
			new_row.item_code = backup.item_code;
			new_row.item_name = backup.item_name;
			new_row.description = backup.description;
			new_row.qty = backup.qty;
			new_row.uom = backup.uom;
			new_row.rate = backup.rate;
			new_row.amount = backup.amount;
			new_row.warehouse = backup.warehouse;
			new_row.material_issue = backup.material_issue;
			new_row.material_issue_status = backup.material_issue_status;
			new_row.expense_account = backup.expense_account;
			new_row.cost_center = backup.cost_center;
			new_row.__is_locked = true;
		});

		// Refresh table
		frm.refresh_field("service_items");

		// Re-apply lock styles
		setTimeout(function () {
			lock_rows_with_submitted_material_issue(frm);
		}, 200);
	}
}

// ฟังก์ชันป้องกันการแก้ไขแถวที่มี Material Issue ที่ submit แล้ว
// ปุ่มเปลี่ยนสถานะ = เส้นทางเดียวกับ ALLOWED_TRANSITIONS ใน technician_portal.py (Draft → In Progress
// ใช้ปุ่ม "รับรถ" ด้านบน) และยิง set_status ตัวเดียวกับพอร์ทัล จึงได้ด่าน _validate_completion ครบ
const STATUS_BUTTONS = {
	"In Progress": [
		{ status: "Ready for Delivery", label: "จบงาน", primary: true },
		{ status: "On Hold", label: "พักงาน" },
	],
	"On Hold": [{ status: "In Progress", label: "ทำงานต่อ", primary: true }],
};

// ชุดเดียวกับ MANAGER_ROLES ของพอร์ทัล — นอกจากนี้ต้องเป็นช่างในใบงาน (ด่านชั้นที่ 2 ของ _get_editable_job)
const STATUS_MANAGER_ROLES = ["Technician Manager", "Service Manager", "System Manager"];
const PARENT_TECHNICIAN_FIELDS = ["technician"].concat(
	Array.from({ length: 9 }, (_, i) => `technician_${i + 2}`)
);

function can_change_status(frm) {
	if (STATUS_MANAGER_ROLES.some((role) => frappe.user.has_role(role))) return true;
	return PARENT_TECHNICIAN_FIELDS.some((f) => frm.doc[f] === frappe.session.user);
}

function add_status_buttons(frm) {
	if (frm.doc.docstatus !== 0 || frm.is_new() || !can_change_status(frm)) return;

	// ย้อนจากจบงานไม่มีในพอร์ทัล — หัวหน้าช่าง/ผู้จัดการแก้การกดจบผิดได้จากฟอร์มเท่านั้น
	if (
		frm.doc.status === "Ready for Delivery" &&
		STATUS_MANAGER_ROLES.some((role) => frappe.user.has_role(role))
	) {
		frm.add_custom_button("เปิดงานอีกครั้ง", function () {
			frappe.confirm("เปิดงานนี้กลับเป็นกำลังซ่อม?", function () {
				frappe.call({
					method: "truck_service_center.truck_service_center.doctype.service_order.service_order.reopen_job",
					args: { service_order: frm.doc.name },
					freeze: true,
					callback: (r) => !r.exc && frm.reload_doc(),
				});
			});
		});
	}

	(STATUS_BUTTONS[frm.doc.status] || []).forEach(function (action) {
		const btn = frm.add_custom_button(action.label, function () {
			const run = () => call_set_status(frm, action.status);
			const go = () => (frm.is_dirty() ? frm.save().then(run) : run());

			if (action.status === "Ready for Delivery") {
				confirm_complete(frm, go);
			} else {
				frappe.confirm(`ยืนยัน${action.label}?`, go);
			}
		});
		if (action.primary) btn.addClass("btn-primary");
	});
}

function call_set_status(frm, status) {
	frappe.call({
		method: "truck_service_center.api.technician_portal.set_status",
		args: { service_order: frm.doc.name, status: status },
		freeze: true,
		callback: function (r) {
			if (r.exc) return;
			frm.reload_doc();
			frappe.show_alert({ message: __("เปลี่ยนสถานะเรียบร้อย"), indicator: "green" });
		},
	});
}

function confirm_complete(frm, proceed) {
	// เหมือน confirmComplete ของพอร์ทัล: บอกสิ่งที่ยังขาดก่อน (server ตรวจซ้ำใน _validate_completion
	// ซึ่งรวมเรื่องใบเบิกอะไหล่ด้วย) ส่วนเลขไมล์ที่ยังไม่อัปเดตเป็นแค่คำถามยืนยัน
	const missing = [];
	const unfinished = (frm.doc.service_types || []).filter((r) => !r.end_time);
	if (unfinished.length) {
		missing.push(
			`จบงานให้ครบทุกรายการ — ยังไม่จบ: ${unfinished
				.map((r) => frappe.utils.escape_html(r.service_type || "(ไม่ระบุ)"))
				.join(", ")}`
		);
	}
	if (!frm.doc.fuel_level_out) missing.push("สถานะน้ำมันออก");

	if (missing.length) {
		frappe.msgprint({
			title: __("ข้อมูลไม่ครบ"),
			indicator: "orange",
			message: "กรุณาบันทึกข้อมูลต่อไปนี้ก่อนจบงาน<br>" + missing.map((m) => `• ${m}`).join("<br>"),
		});
		return;
	}

	const ask = (baseline) => {
		const mileage = flt(frm.doc.current_mileage);
		const unchanged = !mileage || (baseline && mileage === flt(baseline));
		const msg = unchanged
			? `ยังไม่ได้อัปเดตเลขไมล์ของงานนี้ (ปัจจุบัน ${format_number(mileage)} กม.)<br><br>ยืนยันจบงานโดยไม่เปลี่ยนเลขไมล์?`
			: "ยืนยันจบงานนี้? (สถานะจะเป็นรอส่งมอบรถ)";
		frappe.confirm(msg, proceed);
	};

	if (!frm.doc.vehicle) return ask(null);
	frappe.db.get_value("Vehicle", frm.doc.vehicle, "current_mileage", (r) => ask(r && r.current_mileage));
}

// ชุดเดียวกับ WORK_TIME_EDITOR_ROLES ใน service_order.py — server ตรวจซ้ำใน validate_work_times เสมอ
const WORK_TIME_EDITOR_ROLES = ["Technician Manager", "Service Manager", "System Manager"];

function allow_work_time_editing(frm) {
	// ช่องเวลาตั้งเป็น read-only ใน doctype (ช่างได้เวลาจากปุ่มในพอร์ทัล) ปลดให้เฉพาะ role ที่แก้ได้
	const can_edit = WORK_TIME_EDITOR_ROLES.some((role) => frappe.user.has_role(role));
	const grid = frm.fields_dict.service_types && frm.fields_dict.service_types.grid;
	if (!grid) return;

	["start_time", "end_time"].forEach(function (fieldname) {
		grid.update_docfield_property(fieldname, "read_only", can_edit ? 0 : 1);
	});
}

function can_edit_work_time() {
	return WORK_TIME_EDITOR_ROLES.some((role) => frappe.user.has_role(role));
}

function add_work_time_button(frm) {
	if (frm.doc.docstatus !== 0 || frm.is_new() || !can_edit_work_time()) return;
	if (!(frm.doc.service_types || []).length) return;

	frm.add_custom_button("คีย์เวลาทำงาน", () => open_work_time_dialog(frm));
}

function parse_time_input(text) {
	// รับได้ทั้ง 2030 / 20:30 / 20.30 / 830 / 8 → "20:30" ฯลฯ; ว่างคืน "" ; ผิดรูปคืน null
	const raw = (text || "").trim();
	if (!raw) return "";

	let hours, minutes;
	const parts = raw.split(/[:.\s]/).filter(Boolean);
	if (parts.length === 2) {
		[hours, minutes] = parts;
	} else if (/^\d{1,4}$/.test(raw)) {
		hours = raw.length <= 2 ? raw : raw.slice(0, -2);
		minutes = raw.length <= 2 ? "0" : raw.slice(-2);
	} else {
		return null;
	}

	if (!/^\d{1,2}$/.test(hours) || !/^\d{1,2}$/.test(minutes)) return null;
	const h = cint(hours);
	const m = cint(minutes);
	if (h > 23 || m > 59) return null;
	return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

// ค่าในฐานข้อมูลเป็นเวลาตาม time zone ของระบบ แต่ช่อง Datetime ของ Frappe แสดงตาม time zone ของผู้ใช้
// หน้าต่างคีย์เวลาจึงทำงานเป็นเวลาของผู้ใช้ แล้วแปลงกลับเป็นของระบบตอนบันทึก (แบบเดียวกับ control Datetime)
function work_time_user_moment(text) {
	const tz = frappe.boot.time_zone && frappe.boot.time_zone.user;
	return tz ? moment.tz(text, "YYYY-MM-DD HH:mm", tz) : moment(text, "YYYY-MM-DD HH:mm");
}

function work_time_to_system(m) {
	const tz = frappe.boot.time_zone && frappe.boot.time_zone.system;
	return (tz ? m.clone().tz(tz) : m).format("YYYY-MM-DD HH:mm:ss");
}

function open_work_time_dialog(frm) {
	// แทนการเลื่อน slider ชั่วโมง/นาทีของ datepicker — วันที่ใช้ input date ของเบราว์เซอร์ เวลาพิมพ์ตัวเลข
	// ค่าที่ได้ลงแถวงานแล้ว save ปกติ server ตรวจซ้ำ + ประทับร่องรอยใน validate_work_times
	const rows = frm.doc.service_types || [];
	const split = (value) => {
		if (!value) return { date: "", time: "" };
		const m = frappe.datetime.convert_to_user_tz(value, false);
		return { date: m.format("YYYY-MM-DD"), time: m.format("HH:mm") };
	};

	const body = rows
		.map((row) => {
			const start = split(row.start_time);
			const end = split(row.end_time);
			return `
			<tr data-row="${row.name}">
				<td class="tsc-wt-label">${row.idx}. ${frappe.utils.escape_html(row.service_type || "-")}</td>
				<td><input type="date" class="form-control input-xs" data-f="start_date" value="${start.date}"></td>
				<td><input type="text" class="form-control input-xs tsc-wt-time" data-f="start_time"
					inputmode="numeric" placeholder="20:30" value="${start.time}"></td>
				<td><input type="date" class="form-control input-xs" data-f="end_date" value="${end.date}"></td>
				<td><input type="text" class="form-control input-xs tsc-wt-time" data-f="end_time"
					inputmode="numeric" placeholder="22:00" value="${end.time}"></td>
				<td class="tsc-wt-hours text-right"></td>
			</tr>`;
		})
		.join("");

	const dialog = new frappe.ui.Dialog({
		title: "คีย์เวลาทำงาน",
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "table" }],
		primary_action_label: "บันทึก",
		primary_action: () => save_work_time_dialog(frm, dialog),
	});

	dialog.fields_dict.table.$wrapper.html(`
		<style>
			.tsc-wt-table td { vertical-align: middle; }
			.tsc-wt-table .tsc-wt-time { width: 80px; }
			.tsc-wt-table .is-invalid { border-color: var(--red-500); }
			.tsc-wt-label { max-width: 240px; }
		</style>
		<p class="text-muted small">
			พิมพ์เวลาเป็นตัวเลขได้เลย เช่น 2030, 20:30 หรือ 830 · วันจบเว้นว่างได้ (ใช้วันเดียวกับวันเริ่ม
			และถ้าเวลาจบน้อยกว่าเวลาเริ่มจะถือเป็นวันถัดไป) · ล้างทั้งแถว = ล้างเวลาของงานนั้น
		</p>
		<div style="overflow-x:auto">
			<table class="table table-bordered tsc-wt-table">
				<thead><tr>
					<th>งาน</th><th>วันเริ่ม</th><th>เวลาเริ่ม</th><th>วันจบ</th><th>เวลาจบ</th>
					<th class="text-right">ชม.</th>
				</tr></thead>
				<tbody>${body}</tbody>
			</table>
		</div>
		<div class="text-right"><b>เวลาจริงรวม: <span class="tsc-wt-total">-</span> ชม.</b></div>
	`);

	const $table = dialog.fields_dict.table.$wrapper;
	$table.on("input change", "input", () => read_work_time_dialog($table));
	$table.on("blur", ".tsc-wt-time", function () {
		// จัดรูปให้เห็นว่าระบบเข้าใจว่าเวลาอะไร (2030 → 20:30)
		const parsed = parse_time_input(this.value);
		if (parsed) this.value = parsed;
		read_work_time_dialog($table);
	});

	read_work_time_dialog($table);
	dialog.show();
}

function read_work_time_dialog($table) {
	// อ่านทุกแถว → { name, start, end, error } พร้อมอัปเดตชั่วโมงรายแถวและรวมบนหน้าจอ
	const results = [];
	$table.find("tbody tr").each(function () {
		const $tr = $(this);
		const val = (f) => $tr.find(`[data-f="${f}"]`);
		const start_time = parse_time_input(val("start_time").val());
		const end_time = parse_time_input(val("end_time").val());
		const start_date = val("start_date").val();
		let end_date = val("end_date").val();

		val("start_time").toggleClass("is-invalid", start_time === null);
		val("end_time").toggleClass("is-invalid", end_time === null);

		const result = { name: $tr.data("row"), start: null, end: null, error: null };
		if (start_time === null || end_time === null) {
			result.error = "รูปแบบเวลาไม่ถูกต้อง";
		} else if (!start_date && !start_time && !end_date && !end_time) {
			// ทั้งแถวว่าง = ล้างเวลา
		} else if (!start_date || !start_time) {
			result.error = "ต้องระบุวันและเวลาเริ่ม";
		} else {
			result.start = work_time_user_moment(`${start_date} ${start_time}`);
			if (end_time) {
				if (!end_date) {
					end_date = start_date;
					if (end_time < start_time) {
						end_date = moment(start_date).add(1, "day").format("YYYY-MM-DD");
					}
				}
				result.end = work_time_user_moment(`${end_date} ${end_time}`);
			} else if (end_date) {
				result.error = "ระบุวันจบแล้วต้องระบุเวลาจบด้วย";
			}

			if (result.end && result.end.isBefore(result.start)) result.error = "เวลาจบก่อนเวลาเริ่ม";
			const now = moment();
			if (result.start.isAfter(now) || (result.end && result.end.isAfter(now))) {
				result.error = "เวลาเกินเวลาปัจจุบัน";
			}
		}

		const hours = result.end && !result.error ? result.end.diff(result.start, "minutes") / 60 : null;
		$tr.find(".tsc-wt-hours").html(
			result.error
				? `<span class="text-danger small">${result.error}</span>`
				: hours !== null
				? format_number(hours, null, 2)
				: "-"
		);
		results.push(result);
	});

	// เวลาจริงรวม = เริ่มแรกสุด → จบท้ายสุด (เหมือน compute_actual_time)
	const starts = results.filter((r) => r.start && !r.error).map((r) => r.start);
	const ends = results.filter((r) => r.end && !r.error).map((r) => r.end);
	$table
		.find(".tsc-wt-total")
		.text(
			starts.length && ends.length
				? format_number(moment.max(ends).diff(moment.min(starts), "minutes") / 60, null, 2)
				: "-"
		);

	return results;
}

function save_work_time_dialog(frm, dialog) {
	const results = read_work_time_dialog(dialog.fields_dict.table.$wrapper);
	if (results.some((r) => r.error)) {
		frappe.msgprint({ title: "ข้อมูลไม่ถูกต้อง", indicator: "red", message: "กรุณาแก้แถวที่มีข้อความสีแดงก่อนบันทึก" });
		return;
	}

	// เทียบเป็นเวลาของระบบระดับนาที (ตัดวินาทีทิ้ง)
	const fmt = (m) => (m ? work_time_to_system(m) : null);
	const same = (a, b) => (a ? a.slice(0, 16) : null) === (b ? fmt(b).slice(0, 16) : null);

	let changed = 0;
	results.forEach((r) => {
		const row = locals["Service Order Service Type"][r.name];
		if (!row) return;
		// เทียบระดับนาที — ไม่ทับค่าเดิมที่มีวินาทีจากปุ่มในพอร์ทัลถ้าผู้ใช้ไม่ได้แก้
		if (!same(row.start_time, r.start)) {
			row.start_time = fmt(r.start);
			changed++;
		}
		if (!same(row.end_time, r.end)) {
			row.end_time = fmt(r.end);
			changed++;
		}
	});

	if (!changed) {
		dialog.hide();
		return;
	}

	frm.dirty();
	frm.save().then(() => dialog.hide());
}

function show_manual_work_time_notice(frm) {
	// ร่องรอยให้คนตรวจใบงานเห็นทันทีว่าเวลาจริงมีส่วนที่ไม่ได้มาจากปุ่มในพอร์ทัล
	const rows = (frm.doc.service_types || []).filter((r) => r.time_manually_entered);
	if (!rows.length) return;

	const lines = rows.map(
		(r) =>
			`${frappe.utils.escape_html(r.service_type || "-")} — ${frappe.utils.escape_html(
				r.time_entered_by || "-"
			)} (${frappe.datetime.str_to_user(frappe.datetime.convert_to_user_tz(r.time_entered_on))})`
	);
	frm.dashboard.add_comment(
		`<b>เวลาทำงานถูกคีย์เองในฟอร์ม ${rows.length} รายการ:</b> ${lines.join(" · ")}`,
		"orange",
		true
	);
}

function preview_actual_time(frm) {
	// mirror ของ compute_actual_time ใน service_order.py (ต้องแก้คู่กัน) — ให้เห็นผลก่อน save
	// เริ่มแรกสุด → จบท้ายสุด; ยังไม่มีเวลาเริ่มหรือเวลาจบเลยให้คงค่าเดิมไว้
	const rows = frm.doc.service_types || [];
	const starts = rows.filter((r) => r.start_time).map((r) => moment(r.start_time));
	const ends = rows.filter((r) => r.end_time).map((r) => moment(r.end_time));
	if (!starts.length || !ends.length) return;

	const hours = moment.max(ends).diff(moment.min(starts), "seconds") / 3600;
	frm.set_value("actual_time", flt(hours, 2));
}

function lock_rows_with_submitted_material_issue(frm) {
	if (!frm.doc.service_items) return;
	if (!frm.fields_dict.service_items || !frm.fields_dict.service_items.grid) return;

	frm.doc.service_items.forEach(function (item, idx) {
		let grid_row = frm.fields_dict.service_items.grid.grid_rows[idx];
		if (!grid_row) return;

		// ตรวจสอบว่าควรล็อคแถวนี้หรือไม่
		let should_lock = item.material_issue && item.material_issue_status === "Submitted";

		if (should_lock) {
			// บันทึกค่าเดิมไว้เฉพาะเมื่อล็อค
			item.__locked_old_item_code = item.item_code;
			item.__locked_old_qty = item.qty;
			item.__locked_old_rate = item.rate;
			item.__locked_old_warehouse = item.warehouse;
			item.__is_locked = true;

			// เพิ่มสไตล์เพื่อแสดงว่าแถวนี้ถูกล็อค
			if (grid_row.wrapper) {
				grid_row.wrapper.addClass("locked-row");
				grid_row.wrapper.css("background-color", "#f5f5f5");
				grid_row.wrapper.attr(
					"title",
					"แถวนี้ถูกล็อคเพราะใบเบิกอะไหล่ " + item.material_issue + " ถูก submit แล้ว"
				);

				// Disable checkbox และปุ่มลบสำหรับแถวที่ lock (ไม่ซ่อน แค่ปิดการใช้งาน)
				let $checkbox = grid_row.wrapper.find(".grid-row-check");
				let $deleteBtn = grid_row.wrapper.find(".grid-delete-row");

				$checkbox.prop("disabled", true);
				$checkbox.css("opacity", "0.5");
				$checkbox.css("cursor", "not-allowed");

				$deleteBtn.prop("disabled", true);
				$deleteBtn.css("opacity", "0.5");
				$deleteBtn.css("cursor", "not-allowed");
				$deleteBtn.css("pointer-events", "none");
			}
		} else {
			// ปลดล็อคแถวนี้
			delete item.__locked_old_item_code;
			delete item.__locked_old_qty;
			delete item.__locked_old_rate;
			delete item.__locked_old_warehouse;
			item.__is_locked = false;

			// ลบสไตล์ล็อค
			if (grid_row.wrapper) {
				grid_row.wrapper.removeClass("locked-row");
				grid_row.wrapper.css("background-color", "");
				grid_row.wrapper.removeAttr("title");

				// Enable checkbox และปุ่มลบ
				let $checkbox = grid_row.wrapper.find(".grid-row-check");
				let $deleteBtn = grid_row.wrapper.find(".grid-delete-row");

				$checkbox.prop("disabled", false);
				$checkbox.css("opacity", "");
				$checkbox.css("cursor", "");

				$deleteBtn.prop("disabled", false);
				$deleteBtn.css("opacity", "");
				$deleteBtn.css("cursor", "");
				$deleteBtn.css("pointer-events", "");
			}
		}
	});

	// เก็บ backup ของแถวที่ lock สำหรับ restore
	save_locked_rows_backup(frm);

	// Override ฟังก์ชัน delete สำหรับ grid
	override_grid_delete(frm);
}

// Override ฟังก์ชัน delete ของ grid เพื่อป้องกันการลบแถวที่ lock
function override_grid_delete(frm) {
	let grid = frm.fields_dict.service_items.grid;
	if (!grid || grid.__delete_overridden) return;

	// เก็บฟังก์ชัน delete เดิมไว้
	let original_delete_row = grid.grid_rows_by_docname ? null : null;

	// Override ฟังก์ชัน delete_rows
	let original_delete_rows = grid.delete_rows;
	grid.delete_rows = function () {
		// ตรวจสอบว่ามีแถวที่ lock ถูกเลือกหรือไม่
		let locked_rows = [];
		this.get_selected_children().forEach(function (doc) {
			if (doc.__is_locked) {
				locked_rows.push(doc.item_name || doc.item_code || doc.idx);
			}
		});

		if (locked_rows.length > 0) {
			frappe.msgprint({
				title: __("ไม่สามารถลบได้"),
				indicator: "red",
				message: __(
					"ไม่สามารถลบแถวที่ถูกล็อคได้: {0}<br>กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบ",
					[locked_rows.join(", ")]
				),
			});
			// ยกเลิกการเลือก
			this.select_all_btn && this.select_all_btn.prop("checked", false);
			this.grid_rows.forEach(function (row) {
				row.doc.__checked = 0;
			});
			this.refresh_remove_rows_button();
			return;
		}

		// เรียกฟังก์ชันเดิม
		return original_delete_rows.apply(this, arguments);
	};

	grid.__delete_overridden = true;
}

// ====== Address Helper Functions ======

function set_address_filters(frm) {
	// Filter billing address ตาม customer (ผ่าน Dynamic Link)
	frm.set_query("customer_address", function () {
		return {
			query: "frappe.contacts.doctype.address.address.address_query",
			filters: {
				link_doctype: "Customer",
				link_name: frm.doc.customer || "",
			},
		};
	});

	// Filter shipping address ตาม customer (ผ่าน Dynamic Link)
	frm.set_query("shipping_address_name", function () {
		return {
			query: "frappe.contacts.doctype.address.address.address_query",
			filters: {
				link_doctype: "Customer",
				link_name: frm.doc.customer || "",
			},
		};
	});
}

function fetch_customer_addresses(frm) {
	// ดึง default billing address ของลูกค้า
	frappe.call({
		method: "frappe.contacts.doctype.address.address.get_default_address",
		args: {
			doctype: "Customer",
			name: frm.doc.customer,
		},
		callback: function (r) {
			if (r.message) {
				frm.set_value("customer_address", r.message);
			} else {
				frm.set_value("customer_address", "");
				frm.set_value("address_display", "");
			}
		},
	});

	// ดึง default shipping address ของลูกค้า
	frappe.call({
		method: "truck_service_center.truck_service_center.doctype.service_order.service_order.get_party_shipping_address",
		args: {
			doctype: "Customer",
			name: frm.doc.customer,
		},
		callback: function (r) {
			if (r.message) {
				frm.set_value("shipping_address_name", r.message);
			} else {
				frm.set_value("shipping_address_name", "");
				frm.set_value("shipping_address", "");
			}
		},
	});
}

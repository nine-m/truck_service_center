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
		
		// ตั้งค่า filter สำหรับ address ตาม customer
		set_address_filters(frm);
		
		// แสดงสรุป Material Issues
		show_material_issue_summary(frm);
		
		// Update สถานะ Material Issue ทั้งหมด
		update_material_issue_statuses(frm);
		
		// ป้องกันการแก้ไขแถวที่มี Material Issue ที่ submit แล้ว
		lock_rows_with_submitted_material_issue(frm);
		
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
		
		// ล้างค่ารถถ้าเปลี่ยนลูกค้าและรถที่เลือกไว้ไม่ใช่ของลูกค้านี้
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
	
	// Handler สำหรับสแกนบาร์โค้ดประเภทบริการ
	scan_service_type_barcode: function(frm) {
		let barcode = frm.doc.scan_service_type_barcode;
		if (!barcode) return;
		
		// ค้นหา Service Type จากบาร์โค้ด
		frappe.call({
			method: 'frappe.client.get_value',
			args: {
				doctype: 'Service Type',
				filters: { barcode: barcode, is_active: 1 },
				fieldname: ['name', 'service_type_name', 'service_type_group', 'maintenance_type', 'default_duration', 'labor_rate']
			},
			callback: function(r) {
				// ล้างช่องสแกนก่อน
				frm.set_value('scan_service_type_barcode', '');
				
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
							message: __('ประเภทบริการ "{0}" มีอยู่แล้วในรายการ', [service_type_data.service_type_name]),
							indicator: 'orange'
						});
						return;
					}
					
					// เพิ่ม Service Type ใหม่
					let row = frm.add_child('service_types');
					row.service_type = service_type_data.name;
					row.service_type_group = service_type_data.service_type_group;
					row.maintenance_type = service_type_data.maintenance_type;
					row.estimated_time = service_type_data.default_duration || 0;
					row.labor_charges = service_type_data.labor_rate || 0;
					
					frm.refresh_field('service_types');
					calculate_totals(frm);
					
					frappe.show_alert({
						message: __('เพิ่มประเภทบริการ "{0}" เรียบร้อย', [service_type_data.service_type_name]),
						indicator: 'green'
					});
					
					// ตรวจสอบว่ามีรายการอะไหล่ที่ผูกไว้หรือไม่
					check_and_add_service_type_items(frm, service_type_data.name);
				} else {
					frappe.show_alert({
						message: __('ไม่พบประเภทบริการที่ตรงกับบาร์โค้ด "{0}"', [barcode]),
						indicator: 'red'
					});
				}
			}
		});
	},
	
	// Handler สำหรับสแกนบาร์โค้ดอะไหล่
	scan_item_barcode: function(frm) {
		let barcode = frm.doc.scan_item_barcode;
		if (!barcode) return;
		
		// ค้นหา Item จากบาร์โค้ด (ใช้ฟิลด์ barcodes ของ Item)
		frappe.call({
			method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_item_by_barcode',
			args: {
				barcode: barcode,
				customer: frm.doc.customer
			},
			callback: function(r) {
				// ล้างช่องสแกนก่อน
				frm.set_value('scan_item_barcode', '');
				
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
						frappe.model.set_value(existing_row.doctype, existing_row.name, 'qty', new_qty);
						
						// คำนวณยอดเงินใหม่
						let new_amount = new_qty * flt(existing_row.rate);
						frappe.model.set_value(existing_row.doctype, existing_row.name, 'amount', new_amount);
						
						frm.refresh_field('service_items');
						calculate_totals(frm);
						
						frappe.show_alert({
							message: __('เพิ่มจำนวน "{0}" เป็น {1}', [item_data.item_name, new_qty]),
							indicator: 'green'
						});
					} else {
						// ไม่มีรายการที่ไม่มีใบเบิก หรือเป็นรายการใหม่ ให้สร้างแถวใหม่
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
						
						// แสดงข้อความถ้าราคาเป็น 0
						if (!item_data.rate || item_data.rate === 0) {
							frappe.show_alert({
								message: __('ไม่พบราคาสำหรับสินค้านี้ กรุณาตั้งค่า Item Price'),
								indicator: 'orange'
							});
						}
					}
				} else {
					frappe.show_alert({
						message: __('ไม่พบสินค้าที่ตรงกับบาร์โค้ด "{0}"', [barcode]),
						indicator: 'red'
					});
				}
			}
		});
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
	},
	
	before_save: function(frm) {
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
				if (backup.material_issue && current_material_issues.indexOf(backup.material_issue) === -1) {
					deleted_locked_rows.push(backup);
				}
			}
			
			if (deleted_locked_rows.length > 0) {
				// มีแถวที่ lock ถูกลบ - ต้องหยุดการ save
				let item_names = [];
				for (let k = 0; k < deleted_locked_rows.length; k++) {
					item_names.push(deleted_locked_rows[k].item_name || deleted_locked_rows[k].item_code);
				}
				
				frappe.msgprint({
					title: __('ไม่สามารถบันทึกได้'),
					indicator: 'red',
					message: __('ไม่สามารถลบรายการ "{0}" ได้เพราะมีใบเบิกอะไหล่ที่ถูก submit แล้ว<br>กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบ<br><br>กำลัง reload เอกสาร...', [item_names.join(', ')])
				});
				
				frappe.validated = false;
				
				// Reload document หลังจาก 1.5 วินาที
				setTimeout(function() {
					frm.reload_doc();
				}, 1500);
				
				return false;
			}
		}
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
	
	service_type: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.service_type) {
			// ดึงรายการอะไหล่จาก Service Type
			frappe.call({
				method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_service_type_items',
				args: {
					service_type: row.service_type
				},
				callback: function(r) {
					if (r.message && r.message.length > 0) {
						let items = r.message;
						let item_list = items.map(item => 
							`• ${item.item_name || item.item_code} - จำนวน: ${item.qty} ${item.uom || ''} (฿${item.rate || 0})`
						).join('<br>');
						
						frappe.confirm(
							__('ประเภทบริการ "{0}" มีรายการอะไหล่มาตรฐาน {1} รายการ:<br><br>{2}<br><br>ต้องการเพิ่มรายการอะไหล่เหล่านี้ในใบสั่งงานหรือไม่?', 
								[row.service_type, items.length, item_list]),
							function() {
								// Yes - เพิ่มรายการอะไหล่
								items.forEach(function(item) {
									// ตรวจสอบว่ามี item นี้อยู่แล้วหรือไม่
									let exists = false;
									if (frm.doc.service_items) {
										for (let i = 0; i < frm.doc.service_items.length; i++) {
											if (frm.doc.service_items[i].item_code === item.item_code && !frm.doc.service_items[i].material_issue) {
												// มีอยู่แล้ว และยังไม่มีใบเบิก ให้เพิ่มจำนวน
												frm.doc.service_items[i].qty += item.qty;
												frm.doc.service_items[i].amount = frm.doc.service_items[i].qty * frm.doc.service_items[i].rate;
												exists = true;
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
									}
								});
								
								frm.refresh_field('service_items');
								calculate_totals(frm);
								
								frappe.show_alert({
									message: __('เพิ่มรายการอะไหล่ {0} รายการจาก "{1}" เรียบร้อย', [items.length, row.service_type]),
									indicator: 'green'
								});
							},
							function() {
								// No - ไม่ต้องทำอะไร
							}
						);
					}
				}
			});
		}
	},
	
	labor_charges: function(frm, cdt, cdn) {
		calculate_totals(frm);
	},
	
	estimated_time: function(frm, cdt, cdn) {
		calculate_totals(frm);
	}
});

frappe.ui.form.on('Service Order Item', {
	service_items_add: function(frm) {
		calculate_totals(frm);
	},
	
	service_items_remove: function(frm, cdt, cdn) {
		console.log('=== service_items_remove called ===');
		console.log('frm.__locked_rows_backup:', frm.__locked_rows_backup);
		console.log('frm.doc.service_items:', frm.doc.service_items);
		
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
			
			console.log('current_material_issues:', current_material_issues);
			
			// หาแถวที่หายไป
			let missing_rows = [];
			for (let j = 0; j < frm.__locked_rows_backup.length; j++) {
				let backup = frm.__locked_rows_backup[j];
				console.log('checking backup:', backup.material_issue, 'exists:', current_material_issues.indexOf(backup.material_issue));
				if (backup.material_issue && current_material_issues.indexOf(backup.material_issue) === -1) {
					missing_rows.push(backup);
				}
			}
			
			console.log('missing_rows:', missing_rows);
			
			if (missing_rows.length > 0) {
				// แสดงข้อความเตือน
				let item_names = [];
				for (let k = 0; k < missing_rows.length; k++) {
					item_names.push(missing_rows[k].item_name || missing_rows[k].item_code);
				}
				
				frappe.msgprint({
					title: __('ไม่สามารถลบได้'),
					indicator: 'red',
					message: __('ไม่สามารถลบรายการ "{0}" ได้เพราะมีใบเบิกอะไหล่ที่ถูก submit แล้ว<br>กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบ<br><br>กำลังคืนค่า...', [item_names.join(', ')])
				});
				
				console.log('Calling frm.reload_doc()');
				// Reload document เพื่อคืนค่า
				frm.reload_doc();
				return;
			}
		} else {
			console.log('No locked_rows_backup found');
		}
		
		calculate_totals(frm);
	},
	
	// ป้องกันการแก้ไขเมื่อมี Material Issue ที่ submit แล้ว
	before_service_items_remove: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.__is_locked) {
			frappe.msgprint({
				title: __('ไม่สามารถลบได้'),
				indicator: 'red',
				message: __('ไม่สามารถลบแถวนี้ได้เพราะใบเบิกอะไหล่ {0} ถูก submit แล้ว กรุณายกเลิกใบเบิกอะไหล่ก่อน', 
					['<a href="/app/stock-entry/' + row.material_issue + '" target="_blank">' + row.material_issue + '</a>'])
			});
			frappe.validated = false;
			return false;
		}
	},
	
	// ป้องกันการแก้ไขทุก field ก่อนเข้า edit mode
	form_render: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		let is_locked = row.__is_locked || (row.material_issue && row.material_issue_status === 'Submitted');
		
		if (is_locked) {
			// ทำให้แก้ไขไม่ได้เลย
			lock_specific_row(frm, cdn);
			
			// ซ่อน row-action (มีปุ่ม Delete)
			setTimeout(function() {
				let grid_row = frm.fields_dict.service_items.grid.grid_rows_by_docname[cdn];
				if (grid_row && grid_row.grid_form) {
					$(grid_row.grid_form.wrapper).find('.row-actions').hide();
				}
			}, 50);
		}
	},
	
	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		
		// ป้องกันการแก้ไขถ้าแถวถูกล็อค (Material Issue ที่ submit แล้ว)
		if (row.__is_locked) {
			frappe.show_alert({
				message: __('ไม่สามารถแก้ไขได้เพราะใบเบิกอะไหล่ {0} ถูก submit แล้ว', [row.material_issue]),
				indicator: 'red'
			});
			// คืนค่าเดิมที่บันทึกไว้
			if (row.__locked_old_item_code !== undefined) {
				frappe.model.set_value(cdt, cdn, 'item_code', row.__locked_old_item_code);
			}
			return;
		}
		
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
		let row = locals[cdt][cdn];
		
		// ป้องกันการแก้ไขถ้าแถวถูกล็อค (Material Issue ที่ submit แล้ว)
		if (row.__is_locked) {
			frappe.show_alert({
				message: __('ไม่สามารถแก้ไขจำนวนได้เพราะใบเบิกอะไหล่ {0} ถูก submit แล้ว', [row.material_issue]),
				indicator: 'red'
			});
			// คืนค่าเดิมที่บันทึกไว้
			if (row.__locked_old_qty !== undefined) {
				frappe.model.set_value(cdt, cdn, 'qty', row.__locked_old_qty);
			}
			return;
		}
		
		calculate_item_amount(frm, cdt, cdn);
		calculate_totals(frm);
	},
	
	rate: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		
		// ป้องกันการแก้ไขถ้าแถวถูกล็อค (Material Issue ที่ submit แล้ว)
		if (row.__is_locked) {
			frappe.show_alert({
				message: __('ไม่สามารถแก้ไขราคาได้เพราะใบเบิกอะไหล่ {0} ถูก submit แล้ว', [row.material_issue]),
				indicator: 'red'
			});
			// คืนค่าเดิมที่บันทึกไว้
			if (row.__locked_old_rate !== undefined) {
				frappe.model.set_value(cdt, cdn, 'rate', row.__locked_old_rate);
			}
			return;
		}
		
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
		
		// ถ้ามี Material Issue ให้ดึงสถานะล่าสุด
		if (row.material_issue) {
			frappe.db.get_value('Stock Entry', row.material_issue, 'docstatus', function(r) {
				if (r && r.docstatus !== undefined) {
					let status_map = {0: 'Draft', 1: 'Submitted', 2: 'Cancelled'};
					frappe.model.set_value(cdt, cdn, 'material_issue_status', status_map[r.docstatus]);
					
					// ถ้า Material Issue เป็น Submitted แล้ว ให้ล็อคแถวนี้
					if (r.docstatus === 1) {
						// รอให้ field update เสร็จก่อน
						setTimeout(function() {
							lock_rows_with_submitted_material_issue(frm);
						}, 100);
					}
				}
			});
		} else {
			// ถ้าไม่มี Material Issue ให้ล้างสถานะ
			frappe.model.set_value(cdt, cdn, 'material_issue_status', null);
		}
	}
});

function calculate_item_amount(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let amount = flt(row.qty) * flt(row.rate);
	frappe.model.set_value(cdt, cdn, 'amount', amount);
}

// ฟังก์ชันตรวจสอบและเพิ่มรายการอะไหล่จาก Service Type
function check_and_add_service_type_items(frm, service_type) {
	frappe.call({
		method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_service_type_items',
		args: {
			service_type: service_type
		},
		callback: function(r) {
			if (r.message && r.message.length > 0) {
				let items = r.message;
				let item_list = items.map(item => 
					`• ${item.item_name || item.item_code} - จำนวน: ${item.qty} ${item.uom || ''} (฿${item.rate || 0})`
				).join('<br>');
				
				frappe.confirm(
					__('ประเภทบริการ "{0}" มีรายการอะไหล่มาตรฐาน {1} รายการ:<br><br>{2}<br><br>ต้องการเพิ่มรายการอะไหล่เหล่านี้ในใบสั่งงานหรือไม่?', 
						[service_type, items.length, item_list]),
					function() {
						// Yes - เพิ่มรายการอะไหล่
						add_service_type_items_to_order(frm, items, service_type);
					},
					function() {
						// No - ไม่ต้องทำอะไร
					}
				);
			}
		}
	});
}

// ฟังก์ชันเพิ่มรายการอะไหล่จาก Service Type
function add_service_type_items_to_order(frm, items, service_type) {
	let added_count = 0;
	
	items.forEach(function(item) {
		// ตรวจสอบว่ามี item นี้อยู่แล้วหรือไม่
		let exists = false;
		if (frm.doc.service_items) {
			for (let i = 0; i < frm.doc.service_items.length; i++) {
				if (frm.doc.service_items[i].item_code === item.item_code && !frm.doc.service_items[i].material_issue) {
					// มีอยู่แล้ว และยังไม่มีใบเบิก ให้เพิ่มจำนวน
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
	// ถ้าเป็น document ใหม่ ให้ล้าง HTML และออก
	if (!frm.doc.name || frm.doc.__islocal) {
		if (frm.fields_dict.material_issue_summary && frm.fields_dict.material_issue_summary.$wrapper) {
			frm.fields_dict.material_issue_summary.$wrapper.html('');
		}
		return;
	}
	
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
				// Reload เพื่อ update สถานะ Material Issue
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
				// Reload เพื่อ update สถานะ Material Issue
				cur_frm.reload_doc();
			}
		}
	});
};

// Update สถานะ Material Issue ทั้งหมดจาก database
function update_material_issue_statuses(frm) {
	if (!frm.doc.service_items || frm.doc.__islocal) return;
	
	// รวบรวม Material Issue ที่ต้องตรวจสอบ
	let material_issues = [];
	frm.doc.service_items.forEach(function(item) {
		if (item.material_issue && !material_issues.includes(item.material_issue)) {
			material_issues.push(item.material_issue);
		}
	});
	
	if (material_issues.length === 0) return;
	
	// ดึงสถานะจาก database
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Stock Entry',
			filters: {
				name: ['in', material_issues]
			},
			fields: ['name', 'docstatus']
		},
		callback: function(r) {
			if (r.message) {
				// สร้าง map ของสถานะ
				let status_map = {};
				r.message.forEach(function(entry) {
					if (entry.docstatus === 0) {
						status_map[entry.name] = 'Draft';
					} else if (entry.docstatus === 1) {
						status_map[entry.name] = 'Submitted';
					} else if (entry.docstatus === 2) {
						status_map[entry.name] = 'Cancelled';
					}
				});
				
				// Update สถานะในแต่ละแถว
				let updated = false;
				frm.doc.service_items.forEach(function(item) {
					if (item.material_issue && status_map[item.material_issue]) {
						if (item.material_issue_status !== status_map[item.material_issue]) {
							item.material_issue_status = status_map[item.material_issue];
							updated = true;
						}
					}
				});
				
				// Refresh grid ถ้ามีการเปลี่ยนแปลง
				if (updated) {
					frm.refresh_field('service_items');
					// เรียก lock_rows อีกครั้งหลังจาก update status
					setTimeout(function() {
						lock_rows_with_submitted_material_issue(frm);
					}, 100);
				}
			}
		}
	});
}

// ล็อค field เฉพาะของแถวที่ระบุ
function lock_specific_row(frm, cdn) {
	let grid_row = frm.fields_dict.service_items.grid.grid_rows_by_docname[cdn];
	if (!grid_row) return;
	
	let row = grid_row.doc;
	if (row.material_issue && row.material_issue_status === 'Submitted') {
		// บันทึกค่าเดิมไว้เฉพาะเมื่อล็อค
		row.__locked_old_item_code = row.item_code;
		row.__locked_old_qty = row.qty;
		row.__locked_old_rate = row.rate;
		row.__locked_old_warehouse = row.warehouse;
		row.__is_locked = true;
		
		// เพิ่มสไตล์เพื่อแสดงว่าแถวนี้ถูกล็อค
		if (grid_row.wrapper) {
			grid_row.wrapper.addClass('locked-row');
			grid_row.wrapper.css('background-color', '#f5f5f5');
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
	frm.doc.service_items.forEach(function(item) {
		if (item.__is_locked || (item.material_issue && item.material_issue_status === 'Submitted')) {
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
				idx: item.idx
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
		frm.doc.service_items.forEach(function(item) {
			if (item.material_issue) {
				current_material_issues.push(item.material_issue);
			}
		});
	}
	
	// หาแถวที่หายไป
	let missing_rows = [];
	frm.__locked_rows_backup.forEach(function(backup) {
		if (backup.material_issue && current_material_issues.indexOf(backup.material_issue) === -1) {
			missing_rows.push(backup);
		}
	});
	
	if (missing_rows.length > 0) {
		// แสดงข้อความเตือน
		let item_names = missing_rows.map(function(r) { 
			return r.item_name || r.item_code; 
		}).join(', ');
		
		frappe.msgprint({
			title: __('ไม่สามารถลบได้'),
			indicator: 'red',
			message: __('ไม่สามารถลบรายการ "{0}" ได้เพราะมีใบเบิกอะไหล่ที่ถูก submit แล้ว<br>กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบ', [item_names])
		});
		
		// คืนค่าแถวที่ถูกลบกลับมา
		missing_rows.forEach(function(backup) {
			let new_row = frm.add_child('service_items');
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
		frm.refresh_field('service_items');
		
		// Re-apply lock styles
		setTimeout(function() {
			lock_rows_with_submitted_material_issue(frm);
		}, 200);
	}
}

// ฟังก์ชันป้องกันการแก้ไขแถวที่มี Material Issue ที่ submit แล้ว
function lock_rows_with_submitted_material_issue(frm) {
	if (!frm.doc.service_items) return;
	if (!frm.fields_dict.service_items || !frm.fields_dict.service_items.grid) return;
	
	frm.doc.service_items.forEach(function(item, idx) {
		let grid_row = frm.fields_dict.service_items.grid.grid_rows[idx];
		if (!grid_row) return;
		
		// ตรวจสอบว่าควรล็อคแถวนี้หรือไม่
		let should_lock = item.material_issue && item.material_issue_status === 'Submitted';
		
		if (should_lock) {
			// บันทึกค่าเดิมไว้เฉพาะเมื่อล็อค
			item.__locked_old_item_code = item.item_code;
			item.__locked_old_qty = item.qty;
			item.__locked_old_rate = item.rate;
			item.__locked_old_warehouse = item.warehouse;
			item.__is_locked = true;
			
			// เพิ่มสไตล์เพื่อแสดงว่าแถวนี้ถูกล็อค
			if (grid_row.wrapper) {
				grid_row.wrapper.addClass('locked-row');
				grid_row.wrapper.css('background-color', '#f5f5f5');
				grid_row.wrapper.attr('title', 'แถวนี้ถูกล็อคเพราะใบเบิกอะไหล่ ' + item.material_issue + ' ถูก submit แล้ว');
				
				// Disable checkbox และปุ่มลบสำหรับแถวที่ lock (ไม่ซ่อน แค่ปิดการใช้งาน)
				let $checkbox = grid_row.wrapper.find('.grid-row-check');
				let $deleteBtn = grid_row.wrapper.find('.grid-delete-row');
				
				$checkbox.prop('disabled', true);
				$checkbox.css('opacity', '0.5');
				$checkbox.css('cursor', 'not-allowed');
				
				$deleteBtn.prop('disabled', true);
				$deleteBtn.css('opacity', '0.5');
				$deleteBtn.css('cursor', 'not-allowed');
				$deleteBtn.css('pointer-events', 'none');
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
				grid_row.wrapper.removeClass('locked-row');
				grid_row.wrapper.css('background-color', '');
				grid_row.wrapper.removeAttr('title');
				
				// Enable checkbox และปุ่มลบ
				let $checkbox = grid_row.wrapper.find('.grid-row-check');
				let $deleteBtn = grid_row.wrapper.find('.grid-delete-row');
				
				$checkbox.prop('disabled', false);
				$checkbox.css('opacity', '');
				$checkbox.css('cursor', '');
				
				$deleteBtn.prop('disabled', false);
				$deleteBtn.css('opacity', '');
				$deleteBtn.css('cursor', '');
				$deleteBtn.css('pointer-events', '');
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
	grid.delete_rows = function() {
		// ตรวจสอบว่ามีแถวที่ lock ถูกเลือกหรือไม่
		let locked_rows = [];
		this.get_selected_children().forEach(function(doc) {
			if (doc.__is_locked) {
				locked_rows.push(doc.item_name || doc.item_code || doc.idx);
			}
		});
		
		if (locked_rows.length > 0) {
			frappe.msgprint({
				title: __('ไม่สามารถลบได้'),
				indicator: 'red',
				message: __('ไม่สามารถลบแถวที่ถูกล็อคได้: {0}<br>กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบ', [locked_rows.join(', ')])
			});
			// ยกเลิกการเลือก
			this.select_all_btn && this.select_all_btn.prop('checked', false);
			this.grid_rows.forEach(function(row) {
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
		method: 'truck_service_center.truck_service_center.doctype.service_order.service_order.get_party_shipping_address',
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

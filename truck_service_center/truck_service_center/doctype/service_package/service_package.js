// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Service Package', {
	refresh: function(frm) {
		// เพิ่ม custom action ถ้าต้องการ
	},

	onload: function(frm) {
		// ตั้งค่าเริ่มต้นเมื่อโหลดฟอร์ม
	},

	package_rate: function(frm) {
		// เมื่อ user ใส่ราคาแพ็คเกจ ให้คำนวณส่วนลดกลับ
		if (frm.doc.total_standard_rate && frm.doc.package_rate) {
			let total = frm.doc.total_standard_rate;
			let package_rate = frm.doc.package_rate;
			
			// ตรวจสอบว่าราคาแพ็คเกจไม่เกินราคามาตรฐาน
			if (package_rate > total) {
				frappe.msgprint({
					title: __('Warning'),
					indicator: 'orange',
					message: __('ราคาแพ็คเกจสูงกว่าราคามาตรฐาน')
				});
				return;
			}
			
			// คำนวณส่วนลดเป็น %
			let discount_amount = total - package_rate;
			let discount_percent = (discount_amount / total) * 100;
			
			// อัพเดทส่วนลด (%)
			frm.set_value('discount_percent', discount_percent);
		}
	},

	discount_percent: function(frm) {
		// เมื่อ user แก้ไขส่วนลด (%) ให้คำนวณราคาแพ็คเกจ
		if (frm.doc.total_standard_rate && frm.doc.discount_percent !== undefined) {
			let total = frm.doc.total_standard_rate;
			let discount_percent = frm.doc.discount_percent || 0;
			
			// ตรวจสอบว่าส่วนลดไม่เกิน 100%
			if (discount_percent > 100) {
				frappe.msgprint({
					title: __('Error'),
					indicator: 'red',
					message: __('ส่วนลดไม่สามารถเกิน 100% ได้')
				});
				frm.set_value('discount_percent', 0);
				return;
			}
			
			if (discount_percent < 0) {
				frappe.msgprint({
					title: __('Error'),
					indicator: 'red',
					message: __('ส่วนลดต้องเป็นค่าบวก')
				});
				frm.set_value('discount_percent', 0);
				return;
			}
			
			// คำนวณราคาแพ็คเกจ
			let discount_amount = total * (discount_percent / 100);
			let package_rate = total - discount_amount;
			
			// อัพเดทราคาแพ็คเกจ
			frm.set_value('package_rate', package_rate);
		}
	},

	total_standard_rate: function(frm) {
		// เมื่อราคามาตรฐานรวมเปลี่ยน ให้คำนวณราคาแพ็คเกจใหม่
		if (frm.doc.discount_percent) {
			frm.trigger('discount_percent');
		}
	}
});

frappe.ui.form.on('Service Package Item', {
	package_items_add: function(frm) {
		// เมื่อเพิ่มรายการบริการ
		calculate_package_totals(frm);
	},

	package_items_remove: function(frm) {
		// เมื่อลบรายการบริการ
		calculate_package_totals(frm);
	},

	amount: function(frm, cdt, cdn) {
		// เมื่อยอดรวมของแต่ละรายการเปลี่ยน ให้คำนวณยอดรวมทั้งหมด
		calculate_package_totals(frm);
	}
});

function calculate_package_totals(frm) {
	// คำนวณยอดรวมทั้งหมด
	let total = 0;
	
	if (frm.doc.package_items) {
		frm.doc.package_items.forEach(function(item) {
			total += (item.amount || 0);
		});
	}
	
	frm.set_value('total_standard_rate', total);
}

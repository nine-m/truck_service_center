# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TruckServiceCenterSettings(Document):
	def validate(self):
		# แสดงคำเตือนถ้ายังไม่ได้ตั้งค่า Labor Item
		if not self.labor_item:
			frappe.msgprint(
				"แนะนำให้ตั้งค่า 'รายการสินค้าสำหรับค่าแรง' เพื่อให้สามารถสร้าง Sales Invoice ที่มีค่าแรงได้",
				indicator="orange",
				title="คำแนะนำ"
			)


@frappe.whitelist()
def create_labor_item():
	"""สร้าง Labor Item อัตโนมัติ"""
	# ตรวจสอบว่ามีอยู่แล้วหรือไม่
	existing = frappe.db.exists("Item", {"item_name": "Labor Charge"})
	if existing:
		return existing
	
	# สร้าง Item ใหม่
	item = frappe.new_doc("Item")
	item.item_code = "LABOR-001"
	item.item_name = "Labor Charge"
	item.item_group = "Services"
	item.stock_uom = "Nos"
	item.is_stock_item = 0
	item.is_sales_item = 1
	item.is_service_item = 1
	item.description = "Labor charges for vehicle service"
	
	try:
		item.insert()
		frappe.db.commit()
		return item.name
	except Exception as e:
		frappe.log_error(f"Error creating labor item: {str(e)}")
		frappe.throw(f"ไม่สามารถสร้าง Labor Item ได้: {str(e)}")

# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ServiceOrderItem(Document):
	def validate(self):
		self.check_material_issue_submitted()
	
	def check_material_issue_submitted(self):
		"""ป้องกันการแก้ไขข้อมูลถ้า Material Issue ถูก submit ไปแล้ว"""
		if not self.material_issue:
			return
		
		# ตรวจสอบสถานะของ Material Issue
		material_issue_status = frappe.db.get_value("Stock Entry", self.material_issue, "docstatus")
		
		# ถ้า Material Issue ถูก submit แล้ว (docstatus = 1)
		if material_issue_status == 1:
			# ดึงข้อมูลเดิมจาก database
			if not self.is_new():
				old_doc = self.get_doc_before_save()
				
				# ตรวจสอบว่ามีการเปลี่ยนแปลงใน field ที่สำคัญหรือไม่
				if old_doc:
					changed_fields = []
					
					if old_doc.item_code != self.item_code:
						changed_fields.append("รหัสสินค้า")
					if old_doc.qty != self.qty:
						changed_fields.append("จำนวน")
					if old_doc.rate != self.rate:
						changed_fields.append("ราคา")
					if old_doc.warehouse != self.warehouse:
						changed_fields.append("คลังสินค้า")
					
					if changed_fields:
						frappe.throw(
							f"ไม่สามารถแก้ไข {', '.join(changed_fields)} ได้ "
							f"เนื่องจากใบเบิกอะไหล่ {self.material_issue} ถูก submit ไปแล้ว<br>"
							f"กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการแก้ไข",
							title="ไม่สามารถแก้ไขได้"
						)

# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class RepairPosition(Document):
	def validate(self):
		# ตรวจสอบว่ารหัสตำแหน่งไม่ซ้ำ
		if self.is_new():
			exists = frappe.db.exists("Repair Position", self.position_code)
			if exists:
				frappe.throw(f"รหัสตำแหน่ง {self.position_code} มีอยู่แล้ว")
		
		# แปลงรหัสตำแหน่งเป็นตัวพิมพ์ใหญ่
		if self.position_code:
			self.position_code = self.position_code.upper()

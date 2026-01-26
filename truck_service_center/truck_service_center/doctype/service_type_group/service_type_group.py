# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ServiceTypeGroup(Document):
	def validate(self):
		"""ตรวจสอบความถูกต้องของข้อมูล"""
		self.validate_group_code()
	
	def validate_group_code(self):
		"""ตรวจสอบรูปแบบรหัสกลุ่ม"""
		if self.group_code:
			self.group_code = self.group_code.upper()


@frappe.whitelist()
def get_active_groups():
	"""ดึงรายการกลุ่มบริการที่เปิดใช้งาน"""
	groups = frappe.get_all(
		"Service Type Group",
		filters={"is_active": 1},
		fields=["name", "group_code", "group_name"],
		order_by="group_code"
	)
	return groups

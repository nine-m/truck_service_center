# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ServiceBay(Document):
	def validate(self):
		self.validate_name_not_blank()

	def validate_name_not_blank(self):
		"""ชื่อช่องจอดเป็น autoname (field:bay_name) — ช่องว่างล้วนจะได้ชื่อเอกสารเพี้ยน"""
		self.bay_name = (self.bay_name or "").strip()
		if not self.bay_name:
			frappe.throw("กรุณาระบุชื่อช่องจอดซ่อม")


@frappe.whitelist()
def get_active_bays():
	"""ช่องจอดที่เปิดใช้งาน — ใช้ทั้งพอร์ทัลช่างและหน้า desk"""
	return frappe.get_all(
		"Service Bay",
		filters={"is_active": 1},
		fields=["name", "bay_name", "has_pit"],
		order_by="bay_name asc",
	)

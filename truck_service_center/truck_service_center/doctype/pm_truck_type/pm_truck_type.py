# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMTruckType(Document):
	def validate(self):
		self.validate_code()

	def validate_code(self):
		"""รหัสเป็น autoname (field:pm_truck_type_code) — ช่องว่างล้วนจะได้ชื่อเอกสารเพี้ยน

		ต่างจาก BayType.validate_code ตรงที่ไม่บังคับตัวพิมพ์ใหญ่ เพราะรหัสรุ่นรถที่ใช้จริง
		เป็นตัวพิมพ์ผสม (Hino500, SANY-STC160)
		"""
		self.pm_truck_type_code = (self.pm_truck_type_code or "").strip()
		if not self.pm_truck_type_code:
			frappe.throw("กรุณาระบุรหัสประเภทรถ PM")

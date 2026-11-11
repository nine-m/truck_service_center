# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class RepairPosition(Document):
	def before_naming(self):
		# autoname (field:...) ตั้งชื่อเอกสารก่อน validate — ปรับรหัสแค่ใน validate จะได้ชื่อ
		# กับรหัสไม่ตรงกัน (พิมพ์ " pit " → เอกสารชื่อ "pit" แต่รหัส "PIT")
		self.normalize_code()

	def normalize_code(self):
		if self.position_code:
			self.position_code = self.position_code.strip().upper()

	def validate(self):
		# ปรับรหัสก่อนเช็คซ้ำ — ไม่งั้น "a01" กับ "A01" หลุดผ่านการเช็คที่นี่
		self.normalize_code()

		# ตรวจสอบว่ารหัสตำแหน่งไม่ซ้ำ
		if self.is_new():
			exists = frappe.db.exists("Repair Position", self.position_code)
			if exists:
				frappe.throw(f"รหัสตำแหน่ง {self.position_code} มีอยู่แล้ว")

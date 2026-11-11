# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMGroup(Document):
	"""กลุ่มงาน PM ของช่องจอด — Service Bay.pm_group ชี้มาที่นี่ (หนึ่งช่องจอดอยู่ได้หนึ่งกลุ่ม)

	ปฏิทินนัดหมายรวมสถานะ "เต็ม" ของช่องจอดตามกลุ่มนี้ แล้วแสดงป้ายเตือนรายวัน
	(ดู summarize_pm_groups ใน service_appointment.py)
	"""

	def before_naming(self):
		# autoname (field:pm_group_code) ตั้งชื่อก่อน validate — ถ้าปรับรหัสแค่ใน validate
		# พิมพ์ " pm1 " จะได้เอกสารชื่อ "pm1" แต่รหัส "PM1" สองค่าไม่ตรงกันตลอดไป
		self.normalize_code()

	def validate(self):
		self.normalize_code()

	def normalize_code(self):
		# รหัสเป็นข้อความที่โชว์บนปฏิทิน — ตัดช่องว่างและบังคับตัวใหญ่ให้เหมือน Bay Type
		self.pm_group_code = (self.pm_group_code or "").strip().upper()
		if not self.pm_group_code:
			frappe.throw("กรุณาระบุรหัสกลุ่มงาน PM")

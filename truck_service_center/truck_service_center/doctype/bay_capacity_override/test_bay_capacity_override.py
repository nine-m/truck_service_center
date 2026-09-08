# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase


class UnitTestBayCapacityOverride(UnitTestCase):
	"""ทดสอบกฎพื้นฐานของการปรับชั่วโมงรับงานรายวัน (in-memory ไม่ insert)

	การตรวจซ้ำต้องใช้ฐานข้อมูล จึงยกไปทดสอบมือ ที่นี่ตรวจเฉพาะกฎที่เป็น pure
	"""

	def test_negative_capacity_is_rejected(self):
		"""ชั่วโมงรับงานติดลบไม่มีความหมาย — 0 คือปิดทำการอยู่แล้ว"""
		override = frappe.new_doc("Bay Capacity Override")
		override.capacity_hours = -1

		with self.assertRaises(frappe.ValidationError):
			override.validate_capacity_hours()

	def test_zero_capacity_is_allowed(self):
		"""0 = ปิดทำการ ต้องผ่าน"""
		override = frappe.new_doc("Bay Capacity Override")
		override.capacity_hours = 0

		override.validate_capacity_hours()

	def test_positive_capacity_is_allowed(self):
		"""ค่าบวกปกติต้องผ่าน"""
		override = frappe.new_doc("Bay Capacity Override")
		override.capacity_hours = 4.5

		override.validate_capacity_hours()

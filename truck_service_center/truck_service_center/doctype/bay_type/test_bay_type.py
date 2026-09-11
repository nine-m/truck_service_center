# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase


class UnitTestBayType(UnitTestCase):
	"""ทดสอบกฎพื้นฐานของประเภทช่องจอด (in-memory ไม่ insert)"""

	def test_blank_code_is_rejected(self):
		"""รหัสประเภทเป็น autoname — ปล่อยให้ว่างไม่ได้"""
		bay_type = frappe.new_doc("Bay Type")
		bay_type.bay_type_code = "   "

		with self.assertRaises(frappe.ValidationError):
			bay_type.validate_code()

	def test_code_is_trimmed_and_uppercased(self):
		"""patch และเทสต์อ้างรหัส "PIT" ตรง ๆ จึงต้องบังคับรูปแบบตั้งแต่ตอนบันทึก"""
		bay_type = frappe.new_doc("Bay Type")
		bay_type.bay_type_code = "  pit  "

		bay_type.validate_code()

		self.assertEqual(bay_type.bay_type_code, "PIT")

	def test_inactive_type_cannot_be_default(self):
		"""ประเภทที่ปิดใช้งานเป็นค่าเริ่มต้นไม่ได้ — get_default_bay_type กรอง is_active ทิ้ง"""
		bay_type = frappe.new_doc("Bay Type")
		bay_type.bay_type_code = "CRANE"
		bay_type.bay_type_name = "ช่องจอดมีเครน"
		bay_type.is_default = 1
		bay_type.is_active = 0

		with self.assertRaises(frappe.ValidationError):
			bay_type.validate_single_default()

	def test_non_default_type_skips_the_check(self):
		"""ไม่ได้ตั้งเป็นค่าเริ่มต้น → ไม่ต้องแตะฐานข้อมูลและปิดใช้งานได้ตามปกติ"""
		bay_type = frappe.new_doc("Bay Type")
		bay_type.bay_type_code = "CRANE"
		bay_type.bay_type_name = "ช่องจอดมีเครน"
		bay_type.is_default = 0
		bay_type.is_active = 0

		bay_type.validate_single_default()

	def test_default_type_cannot_be_deleted(self):
		"""ทั้งระบบพึ่งประเภทเริ่มต้นเป็นตัวรับงานที่ไม่ระบุประเภท"""
		bay_type = frappe.new_doc("Bay Type")
		bay_type.bay_type_code = "GENERAL"
		bay_type.is_default = 1

		with self.assertRaises(frappe.ValidationError):
			bay_type.on_trash()

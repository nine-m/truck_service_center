# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase


class UnitTestServiceBay(UnitTestCase):
	"""ทดสอบกฎพื้นฐานของช่องจอดซ่อม (in-memory ไม่ insert)"""

	def test_blank_bay_name_is_rejected(self):
		"""ชื่อช่องจอดเป็น autoname — ปล่อยให้ว่างไม่ได้"""
		bay = frappe.new_doc("Service Bay")
		bay.bay_name = "   "

		with self.assertRaises(frappe.ValidationError):
			bay.validate_name_not_blank()

	def test_bay_name_is_trimmed(self):
		"""ตัดช่องว่างหัวท้ายก่อน เพื่อไม่ให้ได้ชื่อเอกสารที่มีช่องว่างติดมา"""
		bay = frappe.new_doc("Service Bay")
		bay.bay_name = "  ช่อง A  "

		bay.validate_name_not_blank()

		self.assertEqual(bay.bay_name, "ช่อง A")

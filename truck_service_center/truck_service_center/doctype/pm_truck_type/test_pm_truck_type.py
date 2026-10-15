# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase


class UnitTestPMTruckType(UnitTestCase):
	"""ทดสอบกฎพื้นฐานของรหัสประเภทรถ PM (in-memory ไม่ insert)"""

	def test_blank_code_is_rejected(self):
		"""รหัสเป็น autoname — ปล่อยให้ว่างไม่ได้"""
		doc = frappe.new_doc("PM Truck Type")
		doc.pm_truck_type_code = "   "

		with self.assertRaises(frappe.ValidationError):
			doc.validate_code()

	def test_code_is_trimmed_but_keeps_case(self):
		"""ตัดช่องว่างหัวท้าย แต่คงตัวพิมพ์ตามที่ผู้ใช้พิมพ์ (รหัสรุ่นรถเป็นตัวพิมพ์ผสม)"""
		doc = frappe.new_doc("PM Truck Type")
		doc.pm_truck_type_code = "  Hino500  "

		doc.validate_code()

		self.assertEqual(doc.pm_truck_type_code, "Hino500")

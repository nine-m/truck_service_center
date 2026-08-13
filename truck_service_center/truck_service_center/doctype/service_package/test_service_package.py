# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase


def make_package(labor_rows=None, part_rows=None, **fields):
	"""สร้าง Service Package ในหน่วยความจำ (ไม่ insert) แล้วคำนวณราคา

	เรียก calculate_totals()/validate_pricing() ตรง ๆ เพื่อทดสอบเฉพาะตรรกะราคา
	โดยข้าม populate_parts_from_service_types() ที่ต้องอ่าน Service Type master
	"""
	pkg = frappe.new_doc("Service Package")
	pkg.update(fields)

	for row in labor_rows or []:
		pkg.append("package_service_types", row)
	for row in part_rows or []:
		pkg.append("package_parts", row)

	pkg.calculate_totals()
	pkg.validate_pricing()
	return pkg


class UnitTestServicePackage(UnitTestCase):
	"""ทดสอบการคำนวณราคาและส่วนลดของ Service Package"""

	def test_standard_rate_is_labor_plus_parts(self):
		"""ราคามาตรฐานรวม = ค่าแรง + ค่าอะไหล่"""
		pkg = make_package(
			labor_rows=[{"labor_rate": 1000}],
			part_rows=[{"qty": 2, "rate": 250}],
		)
		self.assertEqual(pkg.total_labor_rate, 1000)
		self.assertEqual(pkg.total_parts_amount, 500)
		self.assertEqual(pkg.total_standard_rate, 1500)

	# ---------- ไม่ใส่ส่วนลด ----------

	def test_no_discount_defaults_rate_to_standard(self):
		"""ไม่ใส่ทั้งส่วนลดและราคาแพ็คเกจ → ราคาแพ็คเกจ = ราคามาตรฐาน ส่วนลด 0"""
		pkg = make_package(labor_rows=[{"labor_rate": 1000}])
		self.assertEqual(pkg.package_rate, 1000)
		self.assertEqual(pkg.discount_percent, 0)

	def test_no_discount_with_rate_equal_to_standard(self):
		"""ระบุราคาเท่าราคามาตรฐาน โดยไม่ใส่ส่วนลด → ส่วนลด 0 ไม่ error"""
		pkg = make_package(labor_rows=[{"labor_rate": 1000}], package_rate=1000)
		self.assertEqual(pkg.package_rate, 1000)
		self.assertEqual(pkg.discount_percent, 0)

	def test_rate_above_standard_gives_zero_discount(self):
		"""ระบุราคาสูงกว่าราคามาตรฐาน → ส่วนลด 0 (ไม่ติดลบ) และเก็บราคาที่ระบุไว้"""
		pkg = make_package(labor_rows=[{"labor_rate": 1000}], package_rate=1500)
		self.assertEqual(pkg.package_rate, 1500)
		self.assertEqual(pkg.discount_percent, 0)

	# ---------- ใส่ส่วนลด ----------

	def test_rate_below_standard_derives_discount(self):
		"""ระบุราคาต่ำกว่าราคามาตรฐาน → คำนวณ % ส่วนลดย้อนกลับ"""
		pkg = make_package(labor_rows=[{"labor_rate": 1000}], package_rate=800)
		self.assertEqual(pkg.discount_percent, 20)

	def test_discount_percent_sets_rate(self):
		"""กรอก % ส่วนลด → คำนวณราคาแพ็คเกจ"""
		pkg = make_package(labor_rows=[{"labor_rate": 1000}], discount_percent=10)
		self.assertEqual(pkg.package_rate, 900)

	def test_negative_discount_rejected(self):
		"""กรอกส่วนลดติดลบเอง → ยังต้องเตือน"""
		with self.assertRaises(frappe.ValidationError):
			make_package(labor_rows=[{"labor_rate": 1000}], discount_percent=-5)

	def test_discount_over_100_rejected(self):
		"""ส่วนลดเกิน 100% → เตือน"""
		with self.assertRaises(frappe.ValidationError):
			make_package(labor_rows=[{"labor_rate": 1000}], discount_percent=120)

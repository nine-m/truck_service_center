# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.truck_service_center.doctype.service_package.service_package import (
	match_pm_packages,
)


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

	def test_typed_rate_kept_with_rounded_percent(self):
		"""คีย์ราคา 5,000 จาก 7,250 (ฟอร์มตั้ง % = 31.03 ให้) → ราคายังเป็น 5,000 ไม่ใช่ 5,000.33"""
		pkg = make_package(labor_rows=[{"labor_rate": 7250}], package_rate=5000, discount_percent=31.03)
		self.assertEqual(pkg.package_rate, 5000)
		self.assertEqual(pkg.discount_percent, 31.03)
		self.assertEqual(pkg.get_discount_amount(), 2250)

	def test_changed_percent_recomputes_rate(self):
		"""แก้ % ทีหลัง (ไม่ตรงกับราคาเดิม) → คิดราคาใหม่จาก %"""
		pkg = make_package(labor_rows=[{"labor_rate": 1000}], package_rate=800, discount_percent=25)
		self.assertEqual(pkg.package_rate, 750)

	def test_negative_discount_rejected(self):
		"""กรอกส่วนลดติดลบเอง → ยังต้องเตือน"""
		with self.assertRaises(frappe.ValidationError):
			make_package(labor_rows=[{"labor_rate": 1000}], discount_percent=-5)

	def test_discount_over_100_rejected(self):
		"""ส่วนลดเกิน 100% → เตือน"""
		with self.assertRaises(frappe.ValidationError):
			make_package(labor_rows=[{"labor_rate": 1000}], discount_percent=120)


# รอบตามตัวอย่างของผู้ใช้: Package1 ทุก 10,000 กม. / 500 ชม., Package2 ทุก 50,000 กม. / 2,500 ชม.
PM_PACKAGES = [
	{"name": "PKG-2", "service_interval_km": 50000, "pm_interval_hours": 2500},
	{"name": "PKG-1", "service_interval_km": 10000, "pm_interval_hours": 500},
]


def matched_names(reading, interval_field="service_interval_km", packages=PM_PACKAGES):
	return [pkg["name"] for pkg in match_pm_packages(packages, reading, interval_field)]


class UnitTestPMPackageMatching(UnitTestCase):
	"""ทดสอบการจับคู่แพ็คเกจ PM กับเลขไมล์/ชั่วโมงทำงาน (pure function ไม่แตะ DB)"""

	def test_reading_on_both_cycles_recommends_both(self):
		"""50,000 กม. หารลงตัวทั้งรอบ 10,000 และ 50,000 → แนะนำทั้งสองแพ็คเกจ เรียงรอบน้อยก่อน"""
		self.assertEqual(matched_names(50000), ["PKG-1", "PKG-2"])

	def test_reading_on_small_cycle_only(self):
		self.assertEqual(matched_names(60000), ["PKG-1"])

	def test_unrounded_reading_matches_nothing(self):
		"""ระบบไม่ปัดเลขให้ — ผู้ใช้ต้องใส่เลขกลมเอง (325,759 → 330,000)"""
		self.assertEqual(matched_names(325759), [])
		self.assertEqual(matched_names(330000), ["PKG-1"])

	def test_hours_use_their_own_interval(self):
		self.assertEqual(matched_names(2500, "pm_interval_hours"), ["PKG-1", "PKG-2"])
		self.assertEqual(matched_names(1000, "pm_interval_hours"), ["PKG-1"])

	def test_zero_interval_is_skipped(self):
		"""แพ็คเกจที่ไม่ได้ตั้งรอบของหน่วยนั้น (0) ต้องไม่ถูกแนะนำ — และห้ามหารด้วยศูนย์"""
		packages = [{"name": "KM-ONLY", "service_interval_km": 10000, "pm_interval_hours": 0}]
		self.assertEqual(matched_names(500, "pm_interval_hours", packages), [])

	def test_non_positive_reading_matches_nothing(self):
		self.assertEqual(matched_names(0), [])
		self.assertEqual(matched_names(-10000), [])


class UnitTestPMPackageFields(UnitTestCase):
	"""ทดสอบกฎของ section PM บน Service Package (in-memory ไม่ insert)"""

	def make(self, **fields):
		pkg = frappe.new_doc("Service Package")
		pkg.update(fields)
		return pkg

	def test_blank_pm_section_is_general_package(self):
		self.make().validate_pm_fields()

	def test_pm_package_with_interval_passes(self):
		self.make(pm_truck_type="Hino500", service_interval_km=10000).validate_pm_fields()
		self.make(pm_truck_type="SANY-STC160", pm_interval_hours=500).validate_pm_fields()

	def test_type_without_interval_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make(pm_truck_type="Hino500").validate_pm_fields()

	def test_interval_without_type_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make(service_interval_km=10000).validate_pm_fields()

	def test_negative_interval_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make(
				pm_truck_type="Hino500", service_interval_km=10000, pm_interval_hours=-1
			).validate_pm_fields()

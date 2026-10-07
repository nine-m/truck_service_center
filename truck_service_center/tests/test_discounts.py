# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.discounts import distribute_package_discount, resolve_line_discount


def make_package(labor_rates=(), parts=(), package_rate=0):
	"""แพ็คเกจในหน่วยความจำ — parts เป็น (rate, qty)"""
	return frappe._dict(
		package_rate=package_rate,
		package_service_types=[frappe._dict(labor_rate=rate) for rate in labor_rates],
		package_parts=[frappe._dict(rate=rate, qty=qty) for rate, qty in parts],
	)


def net_total(package, labor, unit):
	labor_net = sum(row.labor_rate - d for row, d in zip(package.package_service_types, labor, strict=True))
	parts_net = sum((row.rate - d) * row.qty for row, d in zip(package.package_parts, unit, strict=True))
	return round(labor_net + parts_net, 2)


class UnitTestResolveLineDiscount(UnitTestCase):
	"""บาทเป็นตัวหลัก % เป็นค่าที่คำนวณไว้แสดง"""

	def test_typed_amount_is_kept(self):
		"""คีย์ลด 100 บาทจาก 300 (ฟอร์มตั้ง % เป็น 33.33 ให้) → ยังลด 100 พอดี ไม่ใช่ 99.99"""
		self.assertEqual(resolve_line_discount(300, 33.33, 100), (33.33, 100))

	def test_typed_percent_computes_amount(self):
		self.assertEqual(resolve_line_discount(300, 33.33, 0), (33.33, 99.99))
		self.assertEqual(resolve_line_discount(300, 10, 0), (10, 30))

	def test_changed_percent_wins_over_stale_amount(self):
		"""แก้ % ทีหลัง (บาทเดิมไม่ตรงกับ % ใหม่แล้ว) → คิดบาทจาก % ใหม่"""
		self.assertEqual(resolve_line_discount(300, 50, 100), (50, 150))

	def test_changed_base_keeps_percent(self):
		"""ราคาฐานเปลี่ยน → คง % ไว้เหมือนพฤติกรรมเดิม"""
		self.assertEqual(resolve_line_discount(400, 33.33, 100), (33.33, 133.32))

	def test_amount_only_derives_percent(self):
		self.assertEqual(resolve_line_discount(300, 0, 50), (16.67, 50))

	def test_no_discount(self):
		self.assertEqual(resolve_line_discount(300, 0, 0), (0, 0))


class UnitTestDistributePackageDiscount(UnitTestCase):
	"""ส่วนลดแพ็คเกจแจกเป็นบาทต่อบรรทัด รวมแล้วตรงราคาแพ็คเกจพอดี"""

	def test_odd_percent_sums_to_package_rate(self):
		"""7,250 ขาย 5,000 (31.03%) — เดิมแถวรวมกันได้ 4,999.99"""
		pkg = make_package(labor_rates=(1000, 750), parts=((1500, 2), (833.33, 3)), package_rate=0)
		pkg.package_rate = 5000
		labor, unit = distribute_package_discount(pkg)
		self.assertEqual(net_total(pkg, labor, unit), 5000)

	def test_three_equal_rows(self):
		"""300 ขาย 200 แบ่ง 3 แถวเท่ากัน — เศษไปลงแถวค่าแรงแถวเดียว"""
		pkg = make_package(labor_rates=(100, 100, 100), package_rate=200)
		labor, unit = distribute_package_discount(pkg)
		self.assertEqual(net_total(pkg, labor, unit), 200)
		self.assertEqual(sorted(labor), [33.33, 33.33, 33.34])

	def test_clean_percent_matches_per_line_percent(self):
		"""แพ็คเกจที่ % ลงตัว (10%) ได้ผลเท่ากับใส่ % ทุกแถวแบบเดิม"""
		pkg = make_package(labor_rates=(2000,), parts=((450, 4), (790, 1)), package_rate=4131)
		labor, unit = distribute_package_discount(pkg)
		self.assertEqual(labor, [200])
		self.assertEqual(unit, [45, 79])

	def test_parts_only_remainder_on_single_qty_part(self):
		pkg = make_package(parts=((100, 1), (100, 1), (100, 1)), package_rate=200)
		labor, unit = distribute_package_discount(pkg)
		self.assertEqual(net_total(pkg, labor, unit), 200)

	def test_no_discount(self):
		pkg = make_package(labor_rates=(500,), parts=((100, 2),), package_rate=700)
		self.assertEqual(distribute_package_discount(pkg), ([0], [0]))

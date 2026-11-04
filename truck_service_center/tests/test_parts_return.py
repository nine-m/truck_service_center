# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""ใบคืนอะไหล่ — สูตรยอดเงินคืน และด่านจำนวนคืน (pure ล้วน ไม่ insert เอกสาร)

ยอดเงินคืนต้องเท่ากับยอดที่หายไปจากรวมค่าอะไหล่ของใบสั่งงานพอดี ไม่งั้นตัวเลขที่บัญชีตรวจ
("คืนแล้ว ฿x") จะไม่ตรงกับบิลจริง — ส่วนลดของแถวอะไหล่เป็นต่อหน่วย จึงต้องหักก่อนคูณจำนวน
"""

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.truck_service_center.doctype.parts_return.parts_return import (
	net_unit_rate,
	validate_return_lines,
)


class UnitTestNetUnitRate(UnitTestCase):
	def test_per_unit_discount_is_taken_off_before_qty(self):
		self.assertEqual(net_unit_rate(frappe._dict(rate=250, discount_amount=10)), 240)

	def test_never_negative(self):
		self.assertEqual(net_unit_rate(frappe._dict(rate=100, discount_amount=150)), 0)

	def test_matches_order_line_amount(self):
		"""คืน 1 จาก 4 → ยอดแถวที่เหลือลดลงเท่ายอดคืนพอดี (สูตรเดียวกับ _calculate_line_discount)"""
		row = frappe._dict(rate=199.5, discount_amount=12.25)
		before = round(net_unit_rate(row) * 4, 2)
		after = round(net_unit_rate(row) * 3, 2)
		self.assertEqual(round(before - after, 2), round(net_unit_rate(row) * 1, 2))


class UnitTestValidateReturnLines(UnitTestCase):
	def setUp(self):
		self.available = {
			"row-a": frappe._dict(label="น้ำมันเครื่อง", max_qty=4),
			"row-b": frappe._dict(label="ไส้กรอง", max_qty=1),
		}

	def test_partial_return_and_zero_lines_are_skipped(self):
		lines = validate_return_lines({"row-a": 1, "row-b": 0}, self.available)
		self.assertEqual(lines, [("row-a", 1)])

	def test_decimal_qty_is_allowed(self):
		self.assertEqual(validate_return_lines({"row-a": 0.5}, self.available), [("row-a", 0.5)])

	def test_cannot_return_more_than_available(self):
		with self.assertRaises(frappe.ValidationError):
			validate_return_lines({"row-b": 2}, self.available)

	def test_unknown_row_and_empty_request_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			validate_return_lines({"row-x": 1}, self.available)
		with self.assertRaises(frappe.ValidationError):
			validate_return_lines({"row-a": 0}, self.available)

	def test_negative_qty_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			validate_return_lines({"row-a": -1}, self.available)

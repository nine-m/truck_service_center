# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase


def make_quotation(tax_type="ราคาแยก VAT", vat_rate=7, labor_rows=None, item_rows=None, discount_amount=0):
	"""สร้าง Repair Quotation ในหน่วยความจำ (ไม่ insert) แล้วคำนวณเงิน

	ตรรกะเงินของใบเสนอราคาเป็นสำเนาของ Service Order (คนละไฟล์) —
	เทสต์ชุดนี้กันสองฝั่งคำนวณไม่ตรงกัน
	"""
	rq = frappe.new_doc("Repair Quotation")
	rq.tax_type = tax_type
	rq.vat_rate = vat_rate
	rq.discount_amount = discount_amount

	for row in labor_rows or []:
		rq.append("service_types", row)
	for row in item_rows or []:
		rq.append("service_items", row)

	rq.calculate_totals()
	return rq


class UnitTestRepairQuotation(UnitTestCase):
	"""ทดสอบการคำนวณเงินของ Repair Quotation: VAT / ส่วนลด"""

	def test_vat_exclusive(self):
		rq = make_quotation(
			labor_rows=[{"labor_charges": 1000}],
			item_rows=[{"qty": 1, "rate": 500}],
		)
		self.assertEqual(rq.net_total, 1500)
		self.assertEqual(rq.tax_amount, 105)
		self.assertEqual(rq.total_amount, 1605)

	def test_vat_inclusive(self):
		rq = make_quotation(tax_type="ราคารวม VAT", labor_rows=[{"labor_charges": 1070}])
		self.assertEqual(rq.tax_amount, 70)
		self.assertEqual(rq.net_total, 1000)
		self.assertEqual(rq.total_amount, 1070)

	def test_no_vat_with_document_discount(self):
		rq = make_quotation(
			tax_type="ไม่คิด VAT",
			labor_rows=[{"labor_charges": 1000}],
			item_rows=[{"qty": 2, "rate": 250}],
			discount_amount=100,
		)
		self.assertEqual(rq.total_amount, 1400)
		self.assertEqual(rq.tax_amount, 0)

	def test_line_discounts(self):
		rq = make_quotation(
			tax_type="ไม่คิด VAT",
			labor_rows=[{"labor_charges": 2000, "discount_percentage": 25}],
			item_rows=[{"qty": 2, "rate": 1000, "discount_percentage": 10}],
		)
		self.assertEqual(rq.labor_charges, 1500)
		self.assertEqual(rq.total_parts_amount, 1800)
		self.assertEqual(rq.total_amount, 3300)

# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase


def make_order(
	tax_type="ราคาแยก VAT",
	vat_rate=7,
	labor_rows=None,
	item_rows=None,
	discount_amount=0,
	**fields,
):
	"""สร้าง Service Order ในหน่วยความจำ (ไม่ insert) แล้วคำนวณเงิน

	เรียก calculate_totals()/calculate_wht() ตรง ๆ เพื่อทดสอบเฉพาะตรรกะเงิน
	โดยไม่โดน fetch_from ของ child (labor_charges ถูกทับจาก Service Type master
	ตอน save) และไม่ต้องพึ่งข้อมูล master ในฐานข้อมูล
	"""
	so = frappe.new_doc("Service Order")
	so.tax_type = tax_type
	so.vat_rate = vat_rate
	so.discount_amount = discount_amount
	so.update(fields)

	for row in labor_rows or []:
		so.append("service_types", row)
	for row in item_rows or []:
		so.append("service_items", row)

	so.calculate_totals()
	so.calculate_wht()
	return so


class UnitTestServiceOrder(UnitTestCase):
	"""ทดสอบการคำนวณเงินของ Service Order: VAT / ส่วนลด / ภาษีหัก ณ ที่จ่าย"""

	# ---------- VAT 3 แบบ ----------

	def test_vat_exclusive(self):
		"""ราคาแยก VAT: คิด VAT 7% เพิ่มจากยอดสุทธิ"""
		so = make_order(
			labor_rows=[{"labor_charges": 1000}],
			item_rows=[{"qty": 1, "rate": 500}],
		)
		self.assertEqual(so.net_total, 1500)
		self.assertEqual(so.tax_amount, 105)
		self.assertEqual(so.total_amount, 1605)

	def test_vat_inclusive(self):
		"""ราคารวม VAT: แยก VAT ออกจากยอดที่กรอก"""
		so = make_order(tax_type="ราคารวม VAT", labor_rows=[{"labor_charges": 1070}])
		self.assertEqual(so.tax_amount, 70)
		self.assertEqual(so.net_total, 1000)
		self.assertEqual(so.total_amount, 1070)

	def test_no_vat(self):
		"""ไม่คิด VAT: ยอดรวม = ยอดก่อนภาษี"""
		so = make_order(tax_type="ไม่คิด VAT", labor_rows=[{"labor_charges": 1234.5}])
		self.assertEqual(so.tax_amount, 0)
		self.assertEqual(so.net_total, 1234.5)
		self.assertEqual(so.total_amount, 1234.5)

	# ---------- ส่วนลดระดับบรรทัด ----------

	def test_item_discount_percentage(self):
		"""กรอก % ส่วนลด → คำนวณส่วนลดต่อหน่วยและยอดหลังส่วนลด"""
		so = make_order(
			tax_type="ไม่คิด VAT",
			item_rows=[{"qty": 2, "rate": 1000, "discount_percentage": 10}],
		)
		item = so.service_items[0]
		self.assertEqual(item.discount_amount, 100)  # ต่อหน่วย
		self.assertEqual(item.amount, 1800)  # (1000-100)*2
		self.assertEqual(so.total_parts_amount, 1800)

	def test_item_discount_amount_backfills_percentage(self):
		"""กรอกส่วนลดเป็นบาท → คำนวณ % ย้อนกลับ"""
		so = make_order(
			tax_type="ไม่คิด VAT",
			item_rows=[{"qty": 1, "rate": 500, "discount_amount": 50}],
		)
		item = so.service_items[0]
		self.assertEqual(item.discount_percentage, 10)
		self.assertEqual(item.amount, 450)

	def test_labor_discount(self):
		"""ส่วนลดค่าแรงรายบรรทัด"""
		so = make_order(
			tax_type="ไม่คิด VAT",
			labor_rows=[{"labor_charges": 2000, "discount_percentage": 25}],
		)
		row = so.service_types[0]
		self.assertEqual(row.discount_amount, 500)
		self.assertEqual(row.amount, 1500)
		self.assertEqual(so.labor_charges, 1500)

	def test_discount_cannot_make_amount_negative(self):
		"""ส่วนลดมากกว่าราคา → ยอดเป็น 0 ไม่ติดลบ"""
		so = make_order(
			tax_type="ไม่คิด VAT",
			item_rows=[{"qty": 1, "rate": 1000, "discount_amount": 1500}],
		)
		self.assertEqual(so.service_items[0].amount, 0)

	def test_document_discount_before_vat(self):
		"""ส่วนลดท้ายบิลหักก่อนคิด VAT"""
		so = make_order(labor_rows=[{"labor_charges": 1000}], discount_amount=100)
		self.assertEqual(so.net_total, 900)
		self.assertEqual(so.tax_amount, 63)
		self.assertEqual(so.total_amount, 963)

	# ---------- ภาษีหัก ณ ที่จ่าย (WHT) ----------

	def test_wht_labor_base_with_document_discount(self):
		"""ฐานค่าแรง: เฉลี่ยส่วนลดท้ายบิลตามสัดส่วนค่าแรงก่อนคิด 3%"""
		so = make_order(
			labor_rows=[{"labor_charges": 1000}],
			item_rows=[{"qty": 1, "rate": 500}],
			discount_amount=150,
			apply_wht=1,
			wht_rate=3,
			wht_base="ค่าแรงเท่านั้น",
		)
		# subtotal 1350, สัดส่วนค่าแรง 1000/1500 → ฐาน 900 → WHT 27
		self.assertEqual(so.wht_amount, 27)
		self.assertEqual(so.total_amount, 1444.5)
		self.assertEqual(so.net_payment_amount, 1417.5)

	def test_wht_whole_bill_base(self):
		"""ฐานทั้งใบ (งานจ้างเหมา): คิดจาก subtotal ทั้งหมด"""
		so = make_order(
			labor_rows=[{"labor_charges": 1000}],
			item_rows=[{"qty": 1, "rate": 500}],
			apply_wht=1,
			wht_rate=3,
			wht_base="ทั้งใบ (ค่าแรง+อะไหล่)",
		)
		self.assertEqual(so.wht_amount, 45)

	def test_wht_strips_vat_from_inclusive_price(self):
		"""ราคารวม VAT: ถอด VAT ออกก่อนคิด WHT (1070 → ฐาน 1000 → 30)"""
		so = make_order(
			tax_type="ราคารวม VAT",
			labor_rows=[{"labor_charges": 1070}],
			apply_wht=1,
			wht_rate=3,
			wht_base="ค่าแรงเท่านั้น",
		)
		self.assertEqual(so.wht_amount, 30)
		self.assertEqual(so.net_payment_amount, 1040)

	def test_wht_disabled(self):
		"""ไม่ติ๊กหัก ณ ที่จ่าย → WHT 0 และยอดรับสุทธิ = ยอดรวม"""
		so = make_order(labor_rows=[{"labor_charges": 1000}])
		self.assertEqual(so.wht_amount, 0)
		self.assertEqual(so.net_payment_amount, so.total_amount)

	def test_wht_rate_falls_back_to_default(self):
		"""ไม่กรอกอัตรา → ใช้ค่าเริ่มต้นจาก Settings (หรือ 3)"""
		so = make_order(
			tax_type="ไม่คิด VAT",
			labor_rows=[{"labor_charges": 1000}],
			apply_wht=1,
			wht_rate=0,
			wht_base="ค่าแรงเท่านั้น",
		)
		self.assertGreater(so.wht_rate, 0)
		self.assertEqual(so.wht_amount, 30)  # default 3%

	# ---------- สถานะการชำระเงิน ----------

	def test_payment_status_from_paid_amount(self):
		so = make_order(tax_type="ไม่คิด VAT", labor_rows=[{"labor_charges": 1000}])

		so.paid_amount = 0
		so.update_payment_status()
		self.assertEqual(so.payment_status, "Unpaid")

		so.paid_amount = 400
		so.update_payment_status()
		self.assertEqual(so.payment_status, "Partially Paid")

		so.paid_amount = 1000
		so.update_payment_status()
		self.assertEqual(so.payment_status, "Paid")

	def test_outstanding_amount(self):
		so = make_order(tax_type="ไม่คิด VAT", labor_rows=[{"labor_charges": 1000}], paid_amount=300)
		self.assertEqual(so.outstanding_amount, 700)

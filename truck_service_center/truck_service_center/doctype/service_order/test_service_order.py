# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.api.technician_portal import _can_manage_row, _validate_completion
from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	can_approve_requisition,
	get_bay_warnings,
	get_user_display_name,
	material_issue_status_label,
	plan_bay_assignment,
	select_group_requisition_rows,
	select_requisition_rows,
	select_unclaimed_requisition_rows,
	split_rows_by_service_type_group,
	validate_requisition_approved,
)
from truck_service_center.www.service_order_job import (
	NO_GROUP_LABEL,
	_build_parts,
	_build_service_rows,
	_group_parts,
)


def stub_db_get_value(stock_items=(), submitted_issues=()):
	"""แทน frappe.db.get_value เฉพาะการค้นที่ collect_material_issue_problems เรียก

	คืน docstatus 0 (Draft) ให้ใบเบิกที่ไม่ได้ระบุว่า submit แล้ว — ตรงกับใบเบิกที่
	พอร์ทัลสร้าง ซึ่งถูก insert เป็น Draft เสมอ
	"""

	def _get_value(doctype, name, fieldname=None, *args, **kwargs):
		if doctype == "Item":
			return 1 if name in stock_items else 0
		if doctype == "Stock Entry":
			return 1 if name in submitted_issues else 0
		return None

	return _get_value


def fake_get_all(responses):
	"""แทน frappe.get_all โดยตอบตาม doctype ไม่ใช่ตามลำดับการเรียก

	side_effect แบบ list ผูกกับจำนวนและลำดับ query ของโค้ดที่ทดสอบ พอโค้ดเพิ่ม/ลด query
	(เช่น โหลด meta ของ doctype ใหม่ ซึ่งยิง get_all ของ Custom DocPerm เอง) เทสต์จะพังทั้งที่
	พฤติกรรมยังถูก — ตอบตาม doctype แทน แล้ว doctype ที่ไม่ได้ระบุถือว่าไม่มีข้อมูล
	"""

	def _get_all(doctype, *args, **kwargs):
		return responses.get(doctype, [])

	return _get_all


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

	# ---------- ผูกอะไหล่กับประเภทบริการ ----------

	def test_orphan_items_removed_with_service_type(self):
		"""ลบประเภทบริการ → อะไหล่ที่ดึงมาจากประเภทนั้นถูกลบตาม"""
		so = make_order(
			labor_rows=[{"service_type": "ST-A"}],
			item_rows=[
				{"qty": 1, "rate": 100, "service_type": "ST-A"},
				{"qty": 1, "rate": 200, "service_type": "ST-B"},  # ประเภทนี้ถูกลบไปแล้ว
			],
		)
		so.remove_orphan_service_type_items()

		self.assertEqual([i.service_type for i in so.service_items], ["ST-A"])

	def test_manual_items_survive_service_type_removal(self):
		"""อะไหล่ที่เพิ่มเอง (service_type ว่าง) ไม่ถูกลบ — ครอบคลุมข้อมูลเก่าก่อนมีฟิลด์นี้ด้วย"""
		so = make_order(
			labor_rows=[],
			item_rows=[
				{"qty": 1, "rate": 100},
				{"qty": 1, "rate": 200, "service_type": "ST-B"},
			],
		)
		so.remove_orphan_service_type_items()

		self.assertEqual(len(so.service_items), 1)
		self.assertFalse(so.service_items[0].service_type)
		self.assertEqual(so.service_items[0].idx, 1)

	def test_submitted_material_issue_blocks_orphan_removal(self):
		"""แถวที่มีใบเบิกซึ่ง submit แล้วลบไม่ได้ ต้องยกเลิกใบเบิกก่อน"""
		so = make_order(
			labor_rows=[],
			item_rows=[
				{
					"qty": 1,
					"rate": 100,
					"service_type": "ST-B",
					"material_issue": "MAT-STE-0001",
					"material_issue_status": "Submitted",
				},
				{"qty": 1, "rate": 200, "service_type": "ST-B", "material_issue_status": "Draft"},
			],
		)
		so.remove_orphan_service_type_items()

		self.assertEqual([i.material_issue for i in so.service_items], ["MAT-STE-0001"])

	def test_package_not_reapplied_when_only_items_remain(self):
		"""ลบประเภทบริการของแพ็คเกจจนหมด → save ซ้ำต้องไม่ดึงอะไหล่มาซ้ำ

		ถ้าการ์ดพัง apply_service_packages จะไป frappe.get_doc แพ็คเกจสมมตินี้
		แล้วโยน DoesNotExistError ทันที เทสต์จึงจับ regression ได้โดยไม่ต้องมีข้อมูลจริง
		"""
		so = make_order(
			labor_rows=[],
			item_rows=[{"qty": 1, "rate": 100, "service_package": "PKG-NOT-IN-DB"}],
		)
		so.append("service_packages", {"service_package": "PKG-NOT-IN-DB"})

		so.apply_service_packages()

		self.assertEqual(len(so.service_items), 1)
		self.assertEqual(len(so.service_types), 0)

	def _order_with_removed_service_type(self):
		"""ใบงานที่เพิ่งลบ ST-B ออก โดยอะไหล่ของ ST-B ยังผูกใบเบิกอยู่"""
		so = make_order(
			labor_rows=[{"service_type": "ST-A"}],
			item_rows=[
				{"qty": 1, "rate": 100, "service_type": "ST-B", "material_issue": "MAT-STE-0001"},
			],
		)
		before = make_order(
			labor_rows=[{"service_type": "ST-A"}, {"service_type": "ST-B"}],
			item_rows=[
				{"qty": 1, "rate": 100, "service_type": "ST-B", "material_issue": "MAT-STE-0001"},
			],
		)
		so._doc_before_save = before
		return so

	def test_cannot_remove_service_type_with_submitted_issue(self):
		"""ลบประเภทบริการที่อะไหล่ถูกเบิกไปแล้วไม่ได้ ต้องยกเลิกใบเบิกก่อน"""
		so = self._order_with_removed_service_type()

		with patch("frappe.get_all", return_value=["MAT-STE-0001"]):
			with self.assertRaises(frappe.ValidationError):
				so.validate_service_type_removal()

	def test_can_remove_service_type_when_issue_not_submitted(self):
		"""ใบเบิกที่ยังไม่ submit ไม่บล็อก — ไม่ต้อง mock เพราะใบเบิกสมมตินี้ไม่มีจริงในฐานข้อมูล"""
		so = self._order_with_removed_service_type()

		so.validate_service_type_removal()  # ต้องไม่โยน

	def test_service_type_still_used_by_another_row_is_not_a_removal(self):
		"""ลบแถวซ้ำของประเภทบริการเดียวกันไม่นับเป็นการลบ อะไหล่ไม่ถูก cascade อยู่แล้ว"""
		so = make_order(
			labor_rows=[{"service_type": "ST-B"}],
			item_rows=[{"qty": 1, "rate": 100, "service_type": "ST-B", "material_issue": "MAT-STE-0001"}],
		)
		so._doc_before_save = make_order(
			labor_rows=[{"service_type": "ST-B"}, {"service_type": "ST-B"}],
			item_rows=[{"qty": 1, "rate": 100, "service_type": "ST-B", "material_issue": "MAT-STE-0001"}],
		)

		with patch("frappe.get_all", return_value=["MAT-STE-0001"]):
			so.validate_service_type_removal()  # ต้องไม่โยน

	# ── ด่านปิดงานจากพอร์ทัลช่าง (technician_portal._validate_completion) ─────────

	def test_portal_completion_requires_actual_time(self):
		"""ปิดงานไม่ได้ถ้ายังไม่ได้ลงเวลาทำงานจริง — ปิดแล้วช่างกลับมาแก้จากพอร์ทัลไม่ได้"""
		so = make_order(actual_time=0, fuel_level_out="เต็ม")

		with self.assertRaises(frappe.ValidationError):
			_validate_completion(so)

	def test_portal_completion_requires_fuel_out(self):
		"""ปิดงานไม่ได้ถ้ายังไม่บันทึกน้ำมันนำส่ง — คู่กับน้ำมันรับเข้าที่บังคับตอนรับรถ"""
		so = make_order(actual_time=2, fuel_level_out=None)

		with self.assertRaises(frappe.ValidationError):
			_validate_completion(so)

	def test_portal_completion_lists_every_missing_field(self):
		"""ขาดทั้งสองอย่างต้องฟ้องพร้อมกัน ช่างจะได้ไม่ต้องกดปิดงานซ้ำหลายรอบ"""
		so = make_order(actual_time=0, fuel_level_out=None)

		with self.assertRaises(frappe.ValidationError) as ctx:
			_validate_completion(so)

		message = str(ctx.exception)
		self.assertIn("เวลาทำงานจริง", message)
		self.assertIn("น้ำมันนำส่ง", message)

	def test_portal_completion_passes_when_complete(self):
		"""ครบแล้วต้องผ่าน — เลขไมล์ไม่ใช่เงื่อนไขบังคับ เป็นแค่คำเตือนฝั่งหน้าเว็บ"""
		so = make_order(actual_time=1.5, fuel_level_out="ครึ่ง", current_mileage=0)

		_validate_completion(so)  # ต้องไม่โยน

	def test_portal_completion_requires_every_service_finished(self):
		"""ยังมีงานที่ไม่ได้กดจบ → ปิดงานไม่ได้ และต้องฟ้องชื่องานนั้น"""
		so = make_order(
			actual_time=2,
			fuel_level_out="เต็ม",
			labor_rows=[
				{"service_type": "ST-A", "end_time": "2026-09-01 10:00:00"},
				{"service_type": "ST-B"},
			],
		)

		with self.assertRaises(frappe.ValidationError) as ctx:
			_validate_completion(so)

		self.assertIn("ST-B", str(ctx.exception))

	def test_portal_completion_passes_when_every_service_finished(self):
		"""ทุกงานกดจบครบ + น้ำมันนำส่ง → ผ่าน"""
		so = make_order(
			actual_time=2,
			fuel_level_out="เต็ม",
			labor_rows=[
				{"service_type": "ST-A", "end_time": "2026-09-01 10:00:00"},
				{"service_type": "ST-B", "end_time": "2026-09-01 11:00:00"},
			],
		)

		_validate_completion(so)  # ต้องไม่โยน

	def test_portal_completion_requires_material_issue(self):
		"""ปิดงานไม่ได้ถ้าอะไหล่ยังไม่ได้เบิก — ของออกจากคลังไม่ครบ และปิดแล้วช่างเบิกเองไม่ได้อีก"""
		so = make_order(
			actual_time=2,
			fuel_level_out="เต็ม",
			item_rows=[{"item_code": "PART-A", "item_name": "ไส้กรองน้ำมัน", "qty": 1, "rate": 100}],
		)

		with patch("frappe.db.get_value", side_effect=stub_db_get_value(stock_items={"PART-A"})):
			with self.assertRaises(frappe.ValidationError) as ctx:
				_validate_completion(so)

		self.assertIn("ไส้กรองน้ำมัน", str(ctx.exception))

	def test_portal_completion_accepts_draft_material_issue(self):
		"""ใบเบิกที่ยังเป็น Draft ต้องผ่าน — ช่าง submit Stock Entry ไม่ได้ ผู้จัดการ submit ทีหลัง"""
		so = make_order(
			actual_time=2,
			fuel_level_out="เต็ม",
			item_rows=[
				{
					"item_code": "PART-A",
					"item_name": "ไส้กรองน้ำมัน",
					"qty": 1,
					"rate": 100,
					"material_issue": "MAT-STE-0001",
				}
			],
		)

		with patch("frappe.db.get_value", side_effect=stub_db_get_value(stock_items={"PART-A"})):
			_validate_completion(so)  # ต้องไม่โยน

	def test_portal_completion_ignores_non_stock_items(self):
		"""ค่าบริการ/ของนอกสต็อกไม่มีใบเบิกและเบิกไม่ได้ ต้องไม่ไปขวางการปิดงาน"""
		so = make_order(
			actual_time=2,
			fuel_level_out="เต็ม",
			item_rows=[{"item_code": "SERVICE-FEE", "item_name": "ค่าบริการ", "qty": 1, "rate": 300}],
		)

		with patch("frappe.db.get_value", side_effect=stub_db_get_value(stock_items=set())):
			_validate_completion(so)  # ต้องไม่โยน

	def test_portal_completion_reports_unissued_parts_with_other_gaps(self):
		"""ขาดหลายอย่างต้องฟ้องพร้อมกัน ช่างจะได้เก็บงานรอบเดียวจบ"""
		so = make_order(
			actual_time=2,
			fuel_level_out=None,
			item_rows=[{"item_code": "PART-A", "item_name": "ไส้กรองน้ำมัน", "qty": 1, "rate": 100}],
		)

		with patch("frappe.db.get_value", side_effect=stub_db_get_value(stock_items={"PART-A"})):
			with self.assertRaises(frappe.ValidationError) as ctx:
				_validate_completion(so)

		message = str(ctx.exception)
		self.assertIn("น้ำมันนำส่ง", message)
		self.assertIn("ใบเบิกอะไหล่", message)

	# ── สถานะใบเบิกที่พอร์ทัลใช้ render (service_order_job) ─────────────────────

	def test_portal_view_flags_only_unissued_stock_parts(self):
		"""needs_issue ต้องเป็นจริงเฉพาะสินค้าคงคลังที่ยังไม่มีใบเบิก"""
		so = make_order(
			item_rows=[
				{"item_code": "PART-A", "item_name": "ไส้กรองน้ำมัน", "qty": 1, "rate": 100},
				{
					"item_code": "PART-B",
					"item_name": "ผ้าเบรก",
					"qty": 1,
					"rate": 200,
					"material_issue": "MAT-STE-0001",
				},
				{"item_code": "SERVICE-FEE", "item_name": "ค่าบริการ", "qty": 1, "rate": 300},
			],
		)

		with patch("frappe.get_all", return_value=["PART-A", "PART-B"]):
			parts = _build_parts(so)

		self.assertEqual([part.needs_issue for part in parts], [True, False, False])

	# ── ชื่อผู้สร้างใบเบิกที่ไปโชว์บนหน้ารายการ Stock Entry ─────────────────────

	def test_display_name_uses_full_name(self):
		"""คอลัมน์นี้มีไว้ให้คนอ่าน จึงต้องเป็นชื่อ ไม่ใช่ user id"""
		with patch("frappe.db.get_value", return_value="สมชาย แรงดี"):
			self.assertEqual(get_user_display_name("somchai@example.com"), "สมชาย แรงดี")

	def test_display_name_falls_back_to_user_id(self):
		"""ยังไม่ได้ตั้งชื่อเต็ม ต้องได้ user id ไม่ใช่ช่องว่างที่ดูเหมือนข้อมูลหาย"""
		with patch("frappe.db.get_value", return_value=None):
			self.assertEqual(get_user_display_name("somchai@example.com"), "somchai@example.com")

	def test_display_name_is_blank_without_user(self):
		"""ไม่มี user ก็ไม่ต้องเดา"""
		self.assertIsNone(get_user_display_name(None))

	# ── กลุ่ม "อะไหล่อื่น ๆ" ต้องเบิกได้ ไม่งั้นปิดงานไม่ได้ตลอดไป ────────────────

	def test_unclaimed_rows_are_parts_no_service_row_can_requisition(self):
		"""อะไหล่ที่ไม่มี service_type ไม่มีปุ่มรายงานไหนเบิกให้ได้ ต้องตกมากลุ่มนี้"""
		so = make_order(
			labor_rows=[{"service_type": "ST-A"}],
			item_rows=[
				{"item_code": "PART-A", "service_type": "ST-A"},
				{"item_code": "PART-B"},
			],
		)

		rows = select_unclaimed_requisition_rows(so)

		self.assertEqual([row.item_code for row in rows], ["PART-B"])

	def test_unclaimed_rows_skip_already_issued(self):
		"""เบิกไปแล้วต้องไม่ถูกดึงมาเบิกซ้ำ"""
		so = make_order(item_rows=[{"item_code": "PART-B", "material_issue": "MAT-STE-0001"}])

		self.assertEqual(select_unclaimed_requisition_rows(so), [])

	def test_unclaimed_rows_include_mismatched_package(self):
		"""service_type ตรงแต่แพ็คเกจไม่ตรง แถวงานนั้นก็เบิกให้ไม่ได้ ต้องตกมากลุ่มนี้"""
		so = make_order(
			labor_rows=[{"service_type": "ST-A", "service_package": "PKG-1"}],
			item_rows=[{"item_code": "PART-A", "service_type": "ST-A", "service_package": "PKG-2"}],
		)

		self.assertEqual([row.item_code for row in select_unclaimed_requisition_rows(so)], ["PART-A"])

	def test_unclaimed_rows_exclude_what_a_service_row_can_take(self):
		"""ของที่แถวงานเบิกได้อยู่แล้วต้องไม่ถูกนับซ้ำในกลุ่มอะไหล่อื่น"""
		so = make_order(
			labor_rows=[{"service_type": "ST-A", "service_package": "PKG-1"}],
			item_rows=[{"item_code": "PART-A", "service_type": "ST-A", "service_package": "PKG-1"}],
		)

		self.assertEqual(select_unclaimed_requisition_rows(so), [])

	def test_portal_view_shows_requisition_button_for_leftover_group(self):
		"""กลุ่มอะไหล่อื่นต้องมีปุ่มเบิก — เดิม pending ถูกตรึงเป็น 0 ปุ่มจึงไม่เคยขึ้น"""
		so = make_order(item_rows=[{"item_code": "PART-B", "item_name": "ผ้าเบรก", "qty": 1, "rate": 1}])

		with patch("frappe.get_all", return_value=["PART-B"]):
			parts = _build_parts(so)

		groups = _group_parts([], parts)

		self.assertEqual(groups[0].label, NO_GROUP_LABEL)
		self.assertEqual(groups[0].pending, 1)
		# กลุ่มว่างไม่ผูกกับแถวไหน — ใครอยู่ในใบงานก็ขอเบิกได้ (ด่านจริงคือ _get_group_job)
		self.assertTrue(groups[0].can_request)

	def test_portal_view_hides_requisition_button_for_service_only_group(self):
		"""กลุ่มที่มีแต่ค่าบริการต้องไม่โชว์ปุ่มสร้างใบเบิก — กดไปก็ throw ว่าไม่มีอะไรให้เบิก"""
		so = make_order(
			item_rows=[
				{
					"item_code": "SERVICE-FEE",
					"item_name": "ค่าบริการ",
					"qty": 1,
					"rate": 300,
					"service_type": "ST-A",
				}
			],
		)

		with patch("frappe.get_all", return_value=[]):
			parts = _build_parts(so)

		groups = _group_parts([frappe._dict(name="row1", label="ST-A", package=None)], parts)

		self.assertEqual(groups[0].pending, 0)

	# ── เวลาทำงานจริงคำนวณจากเวลาเริ่ม-จบของงานแต่ละรายการ ──────────────────────

	def test_actual_time_spans_earliest_start_to_latest_end(self):
		"""เวลาจริงเป็น wall-clock: งานที่ทำขนานกันต้องไม่ถูกนับซ้ำ"""
		so = make_order(
			labor_rows=[
				{"start_time": "2026-09-01 09:00:00", "end_time": "2026-09-01 11:00:00"},
				{"start_time": "2026-09-01 10:00:00", "end_time": "2026-09-01 12:30:00"},
			],
		)

		so.compute_actual_time()

		# 09:00 → 12:30 = 3.5 ชม. (ไม่ใช่ 2 + 2.5 = 4.5)
		self.assertEqual(so.actual_time, 3.5)

	def test_actual_time_untouched_when_no_timestamps(self):
		"""ใบเก่าที่ไม่มี timestamp เลย ค่าที่กรอกมือไว้ต้องไม่ถูกแตะ

		เป็นตัวกันไม่ให้ใบเก่า submit ไม่ผ่านด่าน actual_time > 0 ใน before_submit
		"""
		so = make_order(actual_time=4, labor_rows=[{"service_type": "ST-A"}])

		so.compute_actual_time()

		self.assertEqual(so.actual_time, 4)

	def test_actual_time_ignores_rows_started_but_not_finished(self):
		"""แถวที่เริ่มแล้วยังไม่จบ ไม่นับเป็นเวลาจบ แต่ยังนับเป็นเวลาเริ่มได้"""
		so = make_order(
			labor_rows=[
				{"start_time": "2026-09-01 08:00:00"},
				{"start_time": "2026-09-01 09:00:00", "end_time": "2026-09-01 10:00:00"},
			],
		)

		so.compute_actual_time()

		# เริ่มแรกสุด 08:00 → จบท้ายสุด 10:00
		self.assertEqual(so.actual_time, 2)

	def test_actual_time_not_set_when_nothing_finished(self):
		"""มีแต่เวลาเริ่ม ยังไม่มีใครจบ → ยังคำนวณไม่ได้ ต้องไม่ทับค่าเดิม"""
		so = make_order(actual_time=1.5, labor_rows=[{"start_time": "2026-09-01 08:00:00"}])

		so.compute_actual_time()

		self.assertEqual(so.actual_time, 1.5)

	# ── ส่วนลดรายบรรทัด: บาทเป็นตัวหลัก ───────────────────────────────────────────

	def test_labor_discount_in_baht_has_no_satang(self):
		"""ค่าแรง 300 คีย์ลด 100 บาท (ฟอร์มตั้ง % = 33.33 ให้) → ยอด 200.00 ไม่ใช่ 200.01"""
		so = make_order(
			labor_rows=[{"labor_charges": 300, "discount_percentage": 33.33, "discount_amount": 100}]
		)
		row = so.service_types[0]
		self.assertEqual(row.discount_amount, 100)
		self.assertEqual(row.amount, 200)
		self.assertEqual(so.labor_charges, 200)

	def test_part_discount_in_baht_has_no_satang(self):
		so = make_order(
			item_rows=[
				{
					"item_code": "X",
					"qty": 2,
					"rate": 300,
					"discount_percentage": 33.33,
					"discount_amount": 100,
				}
			]
		)
		self.assertEqual(so.service_items[0].amount, 400)

	def test_labor_discount_in_percent_still_works(self):
		so = make_order(labor_rows=[{"labor_charges": 300, "discount_percentage": 10}])
		self.assertEqual(so.service_types[0].discount_amount, 30)
		self.assertEqual(so.service_types[0].amount, 270)

	# ── เตือนช่องจอดเฉพาะตอนที่การจัดช่องจอดเปลี่ยน ─────────────────────────────

	def bay_changed(self, before, after):
		"""before/after = (ช่องจอดหลัก, [แถว]) — before None = ใบใหม่"""
		so = make_order(service_bay=after[0], labor_rows=after[1])
		old = make_order(service_bay=before[0], labor_rows=before[1]) if before else None
		with patch.object(so, "get_doc_before_save", return_value=old):
			return so.bay_assignment_changed()

	def test_bay_warning_skipped_when_bays_unchanged(self):
		"""แก้เรื่องอื่นในใบงาน → ไม่เตือนช่องจอดซ้ำ"""
		rows = [{"name": "r1", "service_type": "ST-A", "service_bay": "BAY-01", "remark": "เดิม"}]
		changed = [{**rows[0], "remark": "แก้หมายเหตุ"}]
		self.assertFalse(self.bay_changed(("BAY-01", rows), ("BAY-01", changed)))

	def test_bay_warning_when_row_bay_or_service_type_changes(self):
		rows = [{"name": "r1", "service_type": "ST-A", "service_bay": "BAY-01"}]
		self.assertTrue(
			self.bay_changed(("BAY-01", rows), ("BAY-01", [{**rows[0], "service_bay": "BAY-02"}]))
		)
		self.assertTrue(self.bay_changed(("BAY-01", rows), ("BAY-01", [{**rows[0], "service_type": "ST-B"}])))

	def test_bay_warning_when_main_bay_changes_or_row_added(self):
		rows = [{"name": "r1", "service_type": "ST-A", "service_bay": "BAY-01"}]
		self.assertTrue(self.bay_changed(("BAY-01", rows), ("BAY-02", rows)))
		self.assertTrue(self.bay_changed(("BAY-01", rows), ("BAY-01", [*rows, {"service_type": "ST-B"}])))
		self.assertTrue(self.bay_changed(None, ("BAY-01", rows)))

	# ── สถานะเปลี่ยนได้ผ่านปุ่มเท่านั้น ─────────────────────────────────────────────

	def run_status_check(self, old_status, new_status, allowed=False, **fields):
		"""เรียก validate_status_change โดยจำลองสถานะก่อน save (old_status None = ใบใหม่)"""
		so = make_order(status=new_status, **fields)
		so.flags.allow_status_change = allowed
		before = make_order(status=old_status) if old_status else None

		with (
			patch.object(so, "is_new", return_value=old_status is None),
			patch.object(so, "get_doc_before_save", return_value=before),
		):
			so.validate_status_change()

	def test_user_cannot_pick_status(self):
		with self.assertRaises(frappe.PermissionError):
			self.run_status_check("In Progress", "Ready for Delivery")

	def test_status_button_path_allowed(self):
		"""ปุ่มจบงาน/พักงาน (set_status) และรับรถตั้ง flag ไว้ → เปลี่ยนได้"""
		self.run_status_check("In Progress", "Ready for Delivery", allowed=True)
		self.run_status_check("In Progress", "On Hold", allowed=True)

	def test_unchanged_status_saves_freely(self):
		self.run_status_check("In Progress", "In Progress")

	def test_new_order_must_start_as_draft(self):
		self.run_status_check(None, "Draft")
		with self.assertRaises(frappe.PermissionError):
			self.run_status_check(None, "In Progress")

	def test_amendment_keeps_copied_status(self):
		"""ใบ amend ได้สถานะติดมาจากใบที่ยกเลิก — ไม่ถือว่าผู้ใช้เลือกเอง"""
		self.run_status_check(None, "Completed", amended_from="SO-OLD")

	def test_button_path_still_cannot_reach_completed(self):
		"""แม้มี flag ก็ยังเลือก Completed ระหว่าง draft ไม่ได้ (เกิดจาก submit เท่านั้น)"""
		with self.assertRaises(frappe.ValidationError):
			self.run_status_check("Ready for Delivery", "Completed", allowed=True)

	# ── คีย์เวลาเริ่ม-จบเองในฟอร์ม (หัวหน้าช่าง/ผู้ดูแลระบบ) ──────────────────────

	def run_work_time_check(self, before_rows, after_rows, roles=("Technician",), portal=False, **fields):
		"""เรียก validate_work_times โดยจำลองแถวก่อน save และ role ของผู้ใช้"""
		so = make_order(labor_rows=after_rows, **fields)
		before = make_order(labor_rows=before_rows) if before_rows is not None else None
		so.flags.allow_work_time_stamp = portal

		with (
			patch.object(so, "get_doc_before_save", return_value=before),
			patch("frappe.get_roles", return_value=list(roles)),
		):
			so.validate_work_times()

		return so

	def test_technician_cannot_edit_work_time_in_form(self):
		"""ช่างทั่วไปแก้เวลาในฟอร์มไม่ได้ ต้องกดเริ่ม/จบในพอร์ทัล"""
		with self.assertRaises(frappe.PermissionError):
			self.run_work_time_check(
				[{"name": "r1"}],
				[{"name": "r1", "start_time": "2026-09-01 20:00:00"}],
			)

	def test_technician_manager_can_backdate_work_time(self):
		"""หัวหน้าช่างคีย์ย้อนหลังนอกเวลาทำการได้"""
		self.run_work_time_check(
			[{"name": "r1"}],
			[{"name": "r1", "start_time": "2026-09-01 20:00:00", "end_time": "2026-09-01 23:30:00"}],
			roles=("Technician Manager",),
		)

	def test_portal_stamp_allowed_for_technician(self):
		"""ปุ่มเริ่ม/จบในพอร์ทัลตั้ง flag ไว้ ช่างจึง stamp เวลาได้"""
		self.run_work_time_check(
			[{"name": "r1"}],
			[{"name": "r1", "start_time": "2026-09-01 08:00:00"}],
			portal=True,
		)

	def test_unchanged_work_time_does_not_need_role(self):
		"""แก้เรื่องอื่นในใบงาน เวลาเดิมไม่เปลี่ยน → ช่างทั่วไป save ได้ (เศษ microsecond ไม่นับ)"""
		self.run_work_time_check(
			[{"name": "r1", "start_time": "2026-09-01 08:00:00.123456"}],
			[{"name": "r1", "start_time": "2026-09-01 08:00:00", "remark": "แก้หมายเหตุ"}],
		)

	def test_work_time_end_before_start_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.run_work_time_check(
				[{"name": "r1"}],
				[{"name": "r1", "start_time": "2026-09-01 10:00:00", "end_time": "2026-09-01 09:00:00"}],
				roles=("Technician Manager",),
			)

	def test_work_time_end_without_start_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.run_work_time_check(
				[{"name": "r1"}],
				[{"name": "r1", "end_time": "2026-09-01 09:00:00"}],
				roles=("System Manager",),
			)

	def test_work_time_in_future_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.run_work_time_check(
				[{"name": "r1"}],
				[{"name": "r1", "start_time": "2999-01-01 08:00:00"}],
				roles=("Service Manager",),
			)

	def test_new_order_with_work_time_needs_role(self):
		"""ใบใหม่ (ไม่มี doc ก่อน save) ที่มีเวลามาด้วย ถือว่าแก้เวลา"""
		with self.assertRaises(frappe.PermissionError):
			self.run_work_time_check(None, [{"start_time": "2026-09-01 08:00:00"}], roles=("Service User",))

	# ── ร่องรอยการคีย์เวลาเอง ────────────────────────────────────────────────────

	def test_manual_entry_stamps_trace(self):
		"""คีย์เวลาในฟอร์ม → แถวถูกติ๊กว่าคีย์เอง พร้อมผู้คีย์/เวลาที่คีย์ และใบงานถูกติ๊กด้วย"""
		so = self.run_work_time_check(
			[{"name": "r1"}, {"name": "r2"}],
			[{"name": "r1", "start_time": "2026-09-01 20:00:00"}, {"name": "r2"}],
			roles=("Technician Manager",),
		)

		row, untouched = so.service_types
		self.assertEqual(row.time_manually_entered, 1)
		self.assertEqual(row.time_entered_by, frappe.session.user)
		self.assertTrue(row.time_entered_on)
		self.assertFalse(untouched.time_manually_entered)
		self.assertEqual(so.has_manual_work_time, 1)

	def test_portal_stamp_leaves_no_trace(self):
		so = self.run_work_time_check(
			[{"name": "r1"}],
			[{"name": "r1", "start_time": "2026-09-01 08:00:00"}],
			portal=True,
		)

		self.assertFalse(so.service_types[0].time_manually_entered)
		self.assertEqual(so.has_manual_work_time, 0)

	def test_portal_finish_keeps_manual_trace(self):
		"""คีย์เวลาเริ่มเองแล้วช่างกดจบในพอร์ทัล — ยังนับเป็นแถวที่คีย์เอง"""
		trace = {"time_manually_entered": 1, "time_entered_by": "boss@x", "time_entered_on": "2026-09-02"}
		so = self.run_work_time_check(
			[{"name": "r1", "start_time": "2026-09-01 08:00:00", **trace}],
			[{"name": "r1", "start_time": "2026-09-01 08:00:00", "end_time": "2026-09-01 10:00:00", **trace}],
			portal=True,
		)

		self.assertEqual(so.service_types[0].time_manually_entered, 1)
		self.assertEqual(so.service_types[0].time_entered_by, "boss@x")

	def test_reset_clears_manual_trace(self):
		trace = {"time_manually_entered": 1, "time_entered_by": "boss@x", "time_entered_on": "2026-09-02"}
		so = self.run_work_time_check(
			[{"name": "r1", "start_time": "2026-09-01 08:00:00", **trace}],
			[{"name": "r1", **trace}],
			roles=("Technician Manager",),
		)

		self.assertFalse(so.service_types[0].time_manually_entered)
		self.assertIsNone(so.service_types[0].time_entered_by)
		self.assertEqual(so.has_manual_work_time, 0)

	def test_client_cannot_clear_manual_trace(self):
		"""ส่งธงเป็น 0 มาโดยไม่แตะเวลา → server คืนร่องรอยจากรอบก่อน"""
		trace = {"time_manually_entered": 1, "time_entered_by": "boss@x", "time_entered_on": "2026-09-02"}
		so = self.run_work_time_check(
			[{"name": "r1", "start_time": "2026-09-01 08:00:00", **trace}],
			[{"name": "r1", "start_time": "2026-09-01 08:00:00", "time_manually_entered": 0}],
		)

		self.assertEqual(so.service_types[0].time_manually_entered, 1)
		self.assertEqual(so.service_types[0].time_entered_by, "boss@x")
		self.assertEqual(so.has_manual_work_time, 1)

	def test_amendment_keeps_original_trace(self):
		"""ใบ amend ได้เวลาติดมาจากใบเดิม — ไม่ถูกประทับใหม่เป็นชื่อคนที่ amend"""
		so = self.run_work_time_check(
			None,
			[
				{"start_time": "2026-09-01 08:00:00"},
				{
					"start_time": "2026-09-01 09:00:00",
					"time_manually_entered": 1,
					"time_entered_by": "boss@x",
				},
			],
			roles=("Service Manager",),
			amended_from="SO-OLD",
		)

		plain, manual = so.service_types
		self.assertFalse(plain.time_manually_entered)
		self.assertEqual(manual.time_entered_by, "boss@x")
		self.assertEqual(so.has_manual_work_time, 1)

	# ── ช่างจากแถวงาน sync ขึ้นระดับใบงาน ──────────────────────────────────────

	def test_row_technicians_fill_first_free_parent_slots(self):
		"""ช่างจากแถวงานถูกเติมลงช่องว่างแรกของใบงาน โดยไม่ทับของเดิม"""
		so = make_order(
			technician="somchai@example.com",
			labor_rows=[{"technician_1": "somsak@example.com"}],
		)

		so.sync_row_technicians_to_parent()

		self.assertEqual(so.technician, "somchai@example.com")
		self.assertEqual(so.technician_2, "somsak@example.com")

	def test_row_technicians_are_deduped(self):
		"""ช่างคนเดียวรับหลายงาน ต้องขึ้นระดับใบงานแค่ครั้งเดียว"""
		so = make_order(
			labor_rows=[
				{"technician_1": "somsak@example.com", "technician_2": "manee@example.com"},
				{"technician_1": "somsak@example.com"},
			],
		)

		so.sync_row_technicians_to_parent()

		self.assertEqual(so.technician, "somsak@example.com")
		self.assertEqual(so.technician_2, "manee@example.com")
		self.assertIsNone(so.technician_3)

	def test_technician_already_on_parent_is_not_added_twice(self):
		"""ช่างที่อยู่ระดับใบงานอยู่แล้ว ต้องไม่ถูกเติมซ้ำอีกช่อง"""
		so = make_order(
			technician_3="somsak@example.com",
			labor_rows=[{"technician_1": "somsak@example.com"}],
		)

		so.sync_row_technicians_to_parent()

		self.assertEqual(so.technician_3, "somsak@example.com")
		self.assertIsNone(so.technician)

	# ── ช่องจอด ────────────────────────────────────────────────────────────────

	def test_default_bay_fills_only_empty_rows(self):
		"""แถวที่ไม่ระบุช่องจอดได้ช่องจอดหลัก ส่วนแถวที่เจาะจงไว้แล้วไม่ถูกทับ"""
		so = make_order(
			service_bay="BAY-1",
			labor_rows=[{"service_type": "ST-A"}, {"service_type": "ST-B", "service_bay": "BAY-2"}],
		)

		so.apply_default_bay()

		self.assertEqual(so.service_types[0].service_bay, "BAY-1")
		self.assertEqual(so.service_types[1].service_bay, "BAY-2")

	def test_bay_warning_when_bay_busy_on_another_open_order(self):
		"""ช่องจอดหลักถูกใบงานที่ยังเปิดอยู่ใบอื่นใช้ค้างไว้ → เตือน (ไม่บล็อก)"""
		so = make_order(service_bay="BAY-1")

		with patch("frappe.get_all", side_effect=fake_get_all({"Service Order": ["SO-2026-00001"]})):
			warnings = get_bay_warnings(so)

		self.assertEqual(len(warnings), 1)
		self.assertIn("BAY-1", warnings[0])
		self.assertIn("SO-2026-00001", warnings[0])

	def test_bay_warning_when_job_needs_another_bay_type(self):
		"""งานที่ต้องใช้ช่องจอดคนละประเภทกับช่องที่จะได้ใช้จริง → เตือน"""
		so = make_order(service_bay="BAY-1", labor_rows=[{"service_type": "ST-OIL"}])

		with patch(
			"frappe.get_all",
			side_effect=fake_get_all(
				{
					"Service Type": [{"name": "ST-OIL", "bay_type": "PIT"}],
					"Service Bay": [{"name": "BAY-1", "bay_type": "GENERAL"}],
					"Bay Type": [
						{"name": "PIT", "bay_type_name": "ช่องจอดมีหลุมซ่อม"},
						{"name": "GENERAL", "bay_type_name": "ช่องจอดทั่วไป"},
					],
				}
			),
		):
			warnings = get_bay_warnings(so)

		self.assertEqual(len(warnings), 1)
		self.assertIn("ST-OIL", warnings[0])
		self.assertIn("BAY-1", warnings[0])
		# ข้อความที่ผู้ใช้เห็นต้องเป็นชื่อไทย ไม่ใช่รหัสประเภท
		self.assertIn("ช่องจอดมีหลุมซ่อม", warnings[0])
		self.assertIn("ช่องจอดทั่วไป", warnings[0])

	def test_no_bay_warning_when_bay_type_matches(self):
		"""ช่องจอดว่างและเป็นประเภทที่งานต้องการ → ไม่มีคำเตือน"""
		so = make_order(service_bay="BAY-1", labor_rows=[{"service_type": "ST-OIL"}])

		with patch(
			"frappe.get_all",
			side_effect=fake_get_all(
				{
					"Service Type": [{"name": "ST-OIL", "bay_type": "PIT"}],
					"Service Bay": [{"name": "BAY-1", "bay_type": "PIT"}],
				}
			),
		):
			warnings = get_bay_warnings(so)

		self.assertEqual(warnings, [])

	# ── ใบเบิกอะไหล่รายงาน ─────────────────────────────────────────────────────

	def test_requisition_rows_match_service_type(self):
		"""เลือกเฉพาะอะไหล่ของงานนั้น ข้ามของงานอื่นและของที่เบิกไปแล้ว"""
		so = make_order(
			labor_rows=[{"service_type": "ST-A"}],
			item_rows=[
				{"qty": 1, "rate": 100, "service_type": "ST-A"},
				{"qty": 1, "rate": 200, "service_type": "ST-B"},
				{"qty": 1, "rate": 300, "service_type": "ST-A", "material_issue": "MAT-STE-0001"},
			],
		)

		rows = select_requisition_rows(so, so.service_types[0])

		self.assertEqual([row.rate for row in rows], [100])

	def test_requisition_rows_also_match_package(self):
		"""แถวงานที่มาจากแพ็คเกจ ต้องหยิบเฉพาะอะไหล่ของแพ็คเกจเดียวกัน"""
		so = make_order(
			labor_rows=[{"service_type": "ST-A", "service_package": "PKG-1"}],
			item_rows=[
				{"qty": 1, "rate": 100, "service_type": "ST-A", "service_package": "PKG-1"},
				{"qty": 1, "rate": 200, "service_type": "ST-A", "service_package": "PKG-2"},
				{"qty": 1, "rate": 300, "service_type": "ST-A"},
			],
		)

		rows = select_requisition_rows(so, so.service_types[0])

		self.assertEqual([row.rate for row in rows], [100])

	def test_requisition_rows_empty_when_service_type_blank(self):
		"""แถวงานที่ยังไม่เลือกประเภทบริการ จับคู่อะไหล่ไม่ได้"""
		so = make_order(
			labor_rows=[{}],
			item_rows=[{"qty": 1, "rate": 100, "service_type": "ST-A"}],
		)

		self.assertEqual(select_requisition_rows(so, so.service_types[0]), [])


class UnitTestRequisitionApproval(UnitTestCase):
	"""ใบเบิกรวมตามกลุ่มบริการ + ขั้นอนุมัติของหัวหน้างานกลุ่ม"""

	def make_grouped_order(self):
		"""ใบงานที่มีสองงานในกลุ่ม ENG, หนึ่งงานกลุ่ม EL, หนึ่งงานไม่มีกลุ่ม และอะไหล่เพิ่มเอง"""
		return make_order(
			labor_rows=[
				{"service_type": "ST-OIL", "service_type_group": "ENG"},
				{"service_type": "ST-FILTER", "service_type_group": "ENG"},
				{"service_type": "ST-LAMP", "service_type_group": "EL"},
				{"service_type": "ST-MISC"},
			],
			item_rows=[
				{"item_code": "OIL", "service_type": "ST-OIL"},
				{"item_code": "FILTER", "service_type": "ST-FILTER"},
				{"item_code": "BULB", "service_type": "ST-LAMP"},
				{"item_code": "RAG", "service_type": "ST-MISC"},
				{"item_code": "BOLT"},
				{"item_code": "OIL-OLD", "service_type": "ST-OIL", "material_issue": "MAT-STE-0001"},
			],
		)

	# ── รวมใบตามกลุ่ม ─────────────────────────────────────────────────────────

	def test_service_types_in_one_group_share_one_requisition(self):
		"""งานหลายรายการในกลุ่มเดียวกันต้องรวมเป็นใบเดียว ข้ามของที่เบิกไปแล้ว"""
		so = self.make_grouped_order()

		rows = select_group_requisition_rows(so, "ENG")

		self.assertEqual([row.item_code for row in rows], ["OIL", "FILTER"])

	def test_other_group_gets_its_own_requisition(self):
		"""คนละกลุ่ม = คนละผู้อนุมัติ จึงต้องแยกใบ"""
		so = self.make_grouped_order()

		self.assertEqual([row.item_code for row in select_group_requisition_rows(so, "EL")], ["BULB"])

	def test_no_group_bucket_takes_unclaimed_and_ungrouped_parts(self):
		"""อะไหล่ที่ไม่มีงานจับคู่ได้ กับอะไหล่ของงานที่ไม่มีกลุ่ม รวมอยู่ใบ "ไม่มีกลุ่ม" ใบเดียว"""
		so = self.make_grouped_order()

		self.assertEqual([row.item_code for row in select_group_requisition_rows(so, None)], ["RAG", "BOLT"])
		# ค่าว่างจากพอร์ทัลต้องหมายถึงกลุ่มเดียวกัน
		self.assertEqual([row.item_code for row in select_group_requisition_rows(so, "")], ["RAG", "BOLT"])

	def test_group_follows_package_matching(self):
		"""แพ็คเกจไม่ตรงกับแถวงาน = จับคู่ไม่ได้ → ตกไปกลุ่มว่าง เหมือน select_requisition_rows"""
		so = make_order(
			labor_rows=[{"service_type": "ST-OIL", "service_package": "PKG-1", "service_type_group": "ENG"}],
			item_rows=[
				{"item_code": "OIL", "service_type": "ST-OIL", "service_package": "PKG-1"},
				{"item_code": "OIL-2", "service_type": "ST-OIL", "service_package": "PKG-2"},
			],
		)

		self.assertEqual([row.item_code for row in select_group_requisition_rows(so, "ENG")], ["OIL"])
		self.assertEqual([row.item_code for row in select_group_requisition_rows(so, None)], ["OIL-2"])

	def test_split_rows_puts_no_group_last(self):
		"""desk สร้างใบตามลำดับกลุ่ม — กลุ่มว่างไว้ท้ายสุดเสมอ"""
		so = self.make_grouped_order()
		rows = [row for row in so.service_items if not row.material_issue]

		groups = split_rows_by_service_type_group(so, rows)

		self.assertEqual(list(groups), ["EL", "ENG", None])
		self.assertEqual([row.item_code for row in groups["ENG"]], ["OIL", "FILTER"])

	# ── ใครอนุมัติได้ ───────────────────────────────────────────────────────────

	def check_can_approve(self, user, roles, group, supervisors=()):
		stock_entry = frappe._dict(custom_service_type_group=group)
		with (
			patch("frappe.get_roles", return_value=list(roles)),
			patch("frappe.get_all", return_value=list(supervisors)),
		):
			return can_approve_requisition(stock_entry, user)

	def test_group_supervisor_can_approve(self):
		self.assertTrue(
			self.check_can_approve(
				"sup@example.com", ["Technician", "Technician Supervisor"], "ENG", ["sup@example.com"]
			)
		)

	def test_supervisor_of_another_group_cannot_approve(self):
		"""หัวหน้างานอนุมัติได้เฉพาะกลุ่มที่ตัวเองดูแล"""
		self.assertFalse(
			self.check_can_approve(
				"sup@example.com", ["Technician", "Technician Supervisor"], "EL", ["other@example.com"]
			)
		)

	def test_plain_technician_cannot_approve(self):
		"""ช่างส่งใบเบิกไปสต๊อกเองไม่ได้ — ต้องผ่านหัวหน้างานก่อน"""
		self.assertFalse(self.check_can_approve("tech@example.com", ["Technician"], "ENG", []))

	def test_fallback_roles_approve_any_group(self):
		"""หัวหน้าช่าง/ผู้จัดการอนุมัติแทนได้ทุกกลุ่ม แม้ไม่ได้อยู่ในรายชื่อ"""
		for role in ("Technician Manager", "Service Manager", "System Manager"):
			self.assertTrue(self.check_can_approve("boss@example.com", [role], "ENG", []), role)

	def test_no_group_requisition_is_for_fallback_roles_only(self):
		"""ใบไม่มีกลุ่มไม่มีหัวหน้างานกลุ่ม — เหลือแต่หัวหน้าช่าง/ผู้จัดการ"""
		self.assertFalse(
			self.check_can_approve("sup@example.com", ["Technician", "Technician Supervisor"], None)
		)
		self.assertTrue(self.check_can_approve("boss@example.com", ["Technician Manager"], None))

	# ── ด่าน submit ฝั่งสต๊อก ──────────────────────────────────────────────────

	def make_stock_entry(self, status, service_order="SO-2026-00001"):
		return frappe._dict(
			name="MAT-STE-0009",
			custom_service_order=service_order,
			custom_approval_status=status,
			custom_rejection_reason="ของยังมีในรถ" if status == "Rejected" else None,
		)

	def test_pending_requisition_cannot_be_submitted(self):
		with self.assertRaises(frappe.ValidationError):
			validate_requisition_approved(self.make_stock_entry("Pending"))

	def test_rejected_requisition_cannot_be_submitted(self):
		with self.assertRaises(frappe.ValidationError):
			validate_requisition_approved(self.make_stock_entry("Rejected"))

	def test_approved_requisition_can_be_submitted(self):
		validate_requisition_approved(self.make_stock_entry("Approved"))

	def test_legacy_requisition_without_status_passes(self):
		"""ใบเก่าก่อนมีขั้นอนุมัติ (สถานะว่าง) ต้องไม่ติดค้าง"""
		validate_requisition_approved(self.make_stock_entry(None))

	def test_stock_entry_without_service_order_is_untouched(self):
		"""Stock Entry ทั่วไปของสต๊อกที่ไม่ได้มาจากใบสั่งงาน ไม่เกี่ยวกับขั้นอนุมัตินี้"""
		validate_requisition_approved(self.make_stock_entry("Pending", service_order=None))

	# ── สถานะที่แถวอะไหล่เห็น ─────────────────────────────────────────────────

	def test_row_status_reflects_approval_while_draft(self):
		self.assertEqual(material_issue_status_label(0, "Pending"), "Pending Approval")
		self.assertEqual(material_issue_status_label(0, "Rejected"), "Rejected")
		self.assertEqual(material_issue_status_label(0, "Approved"), "Draft")
		self.assertEqual(material_issue_status_label(0, None), "Draft")
		self.assertEqual(material_issue_status_label(1, "Approved"), "Submitted")
		self.assertEqual(material_issue_status_label(2, "Approved"), "Cancelled")

	# ── พอร์ทัล: อะไหล่จัดกลุ่มตามกลุ่มบริการ ─────────────────────────────────

	def build_portal_groups(
		self, so, issues=None, is_manager=False, user="tech@example.com", supervised_groups=frozenset(), job_access=True
	):
		with patch("frappe.get_all", return_value=[row.item_code for row in so.service_items]):
			parts = _build_parts(so)
		service_types = [
			frappe._dict(
				name=row.name or row.service_type,
				label=row.service_type,
				package=row.service_package,
				group=row.service_type_group or "",
				mine=row.technician_1 == user,
			)
			for row in so.service_types
		]
		return _group_parts(
			service_types,
			parts,
			group_names={"ENG": "เครื่องยนต์"},
			issues=issues,
			is_manager=is_manager,
			supervised_groups=supervised_groups,
			job_access=job_access,
		)

	def test_portal_groups_parts_by_service_type_group(self):
		"""หนึ่งกลุ่มบนหน้าจอ = หนึ่งใบขออนุมัติเบิก งานหลายรายการในกลุ่มเดียวกันอยู่กล่องเดียว"""
		so = self.make_grouped_order()

		groups = self.build_portal_groups(so)

		self.assertEqual([group.group for group in groups], ["ENG", "EL", ""])
		self.assertEqual(groups[0].label, "เครื่องยนต์")
		self.assertEqual(groups[0].jobs, ["ST-OIL", "ST-FILTER"])
		self.assertEqual(groups[0].pending, 2)
		self.assertEqual(groups[-1].label, NO_GROUP_LABEL)
		self.assertEqual([part.label for part in groups[-1].parts], ["RAG", "BOLT"])

	def test_portal_request_button_needs_a_row_in_the_group(self):
		"""ช่างที่ไม่ได้อยู่บนงานไหนของกลุ่มจะไม่เห็นปุ่มขออนุมัติเบิกของกลุ่มนั้น"""
		so = self.make_grouped_order()
		so.service_types[0].technician_1 = "tech@example.com"

		groups = {group.group: group for group in self.build_portal_groups(so)}

		self.assertTrue(groups["ENG"].can_request)
		self.assertFalse(groups["EL"].can_request)
		self.assertTrue(groups[""].can_request)

	# ── หัวหน้างานกลุ่ม: จัดการได้เฉพาะงานในกลุ่มที่ตัวเองดูแล ──────────────────

	def test_supervisor_can_request_only_for_own_group(self):
		"""หัวหน้างานที่ไม่ได้อยู่ในใบ ขอเบิกได้เฉพาะกลุ่มตน — กลุ่มว่างเป็นสิทธิ์ระดับใบ จึงขอไม่ได้"""
		so = self.make_grouped_order()

		groups = {
			group.group: group
			for group in self.build_portal_groups(so, supervised_groups={"ENG"}, job_access=False)
		}

		self.assertTrue(groups["ENG"].can_request)
		self.assertFalse(groups["EL"].can_request)
		self.assertFalse(groups[""].can_request)

	def test_supervisor_manages_only_rows_in_own_group(self):
		so = self.make_grouped_order()

		with patch("frappe.get_all", return_value=[]):
			rows = _build_service_rows(so, False, supervised_groups={"ENG"})
			closed = _build_service_rows(so, False, supervised_groups={"ENG"}, doc_open=False)

		self.assertEqual(
			[(row.group, row.can_manage) for row in rows],
			[(row.service_type_group or "", row.service_type_group == "ENG") for row in so.service_types],
		)
		self.assertFalse(any(row.can_manage for row in closed))

	def test_api_row_scope_matches_supervised_groups(self):
		"""ด่านจริงฝั่ง api — แถวไม่มีกลุ่มเป็นของหัวหน้าช่างเท่านั้น"""
		with patch("truck_service_center.api.technician_portal._is_manager", return_value=False):
			self.assertTrue(_can_manage_row(frappe._dict(service_type_group="ENG"), {"ENG"}))
			self.assertFalse(_can_manage_row(frappe._dict(service_type_group="EL"), {"ENG"}))
			self.assertFalse(_can_manage_row(frappe._dict(service_type_group=None), {"ENG"}))
		with patch("truck_service_center.api.technician_portal._is_manager", return_value=True):
			self.assertTrue(_can_manage_row(frappe._dict(service_type_group=None), set()))

	def test_portal_shows_rejected_issue_only_while_group_needs_a_new_request(self):
		"""ใบที่ไม่อนุมัติถูกปลดจากแถวแล้ว — โชว์เหตุผลตามกลุ่มของใบ เฉพาะตอนยังต้องขอใหม่"""
		so = self.make_grouped_order()
		rejected = frappe._dict(name="MAT-STE-0002", group="ENG", status="Rejected", reason="ผิดรุ่น")

		groups = {
			group.group: group for group in self.build_portal_groups(so, issues={"MAT-STE-0002": rejected})
		}

		# MAT-STE-0001 ยังผูกกับแถว OIL-OLD อยู่ ส่วนใบที่ไม่อนุมัติต่อท้ายตามกลุ่มของใบ
		self.assertEqual([issue.name for issue in groups["ENG"].issues], ["MAT-STE-0001", "MAT-STE-0002"])
		self.assertEqual(groups["EL"].issues, [])


def _bay(name, bay_type, free, is_closed=False):
	return {"bay": name, "bay_type": bay_type, "free": free, "is_closed": is_closed}


def _row(name, service_type, start_time=None, service_bay=None):
	return frappe._dict(name=name, service_type=service_type, start_time=start_time, service_bay=service_bay)


class UnitTestPlanBayAssignment(UnitTestCase):
	"""plan_bay_assignment — ตรรกะปุ่ม "จัด Bay อัตโนมัติ" ของใบสั่งงาน (pure ไม่แตะ DB)"""

	TYPES = {"ST-PIT": "PIT", "ST-GEN": None}

	def plan(self, rows, hours, bays, busy=()):
		return plan_bay_assignment(rows, hours, bays, busy, self.TYPES, "GENERAL")

	def test_each_row_gets_a_bay_of_its_type_and_main_bay_is_the_longest_job(self):
		plan = self.plan(
			[_row("r1", "ST-PIT"), _row("r2", "ST-GEN")],
			{"PIT": 2, "GENERAL": 5},
			[_bay("PIT-01", "PIT", 8), _bay("BAY-01", "GENERAL", 8)],
		)
		self.assertEqual(plan["service_bay"], "BAY-01")
		self.assertEqual(plan["row_bays"], {"r1": "PIT-01", "r2": "BAY-01"})

	def test_prefers_a_bay_no_other_open_order_is_holding(self):
		plan = self.plan(
			[_row("r1", "ST-GEN")],
			{"GENERAL": 2},
			[_bay("BAY-01", "GENERAL", 8), _bay("BAY-02", "GENERAL", 3)],
			busy={"BAY-01"},
		)
		self.assertEqual(plan["service_bay"], "BAY-02")

	def test_among_free_bays_picks_the_one_with_room_then_the_emptiest(self):
		bays = [_bay("BAY-01", "GENERAL", 3), _bay("BAY-02", "GENERAL", 6), _bay("BAY-03", "GENERAL", 1, True)]
		plan = self.plan([_row("r1", "ST-GEN")], {"GENERAL": 4}, bays)
		self.assertEqual(plan["service_bay"], "BAY-02")

	def test_falls_back_to_a_busy_bay_rather_than_another_type(self):
		plan = self.plan(
			[_row("r1", "ST-PIT")],
			{"PIT": 2},
			[_bay("PIT-01", "PIT", 8), _bay("BAY-01", "GENERAL", 8)],
			busy={"PIT-01"},
		)
		self.assertEqual(plan["row_bays"], {"r1": "PIT-01"})

	def test_type_without_any_bay_uses_the_main_bay_and_is_reported(self):
		plan = self.plan(
			[_row("r1", "ST-PIT"), _row("r2", "ST-GEN")],
			{"PIT": 1, "GENERAL": 3},
			[_bay("BAY-01", "GENERAL", 8)],
		)
		self.assertEqual(plan["unallocatable"], ["PIT"])
		self.assertEqual(plan["row_bays"], {"r1": "BAY-01", "r2": "BAY-01"})

	def test_started_rows_are_not_moved(self):
		plan = self.plan(
			[_row("r1", "ST-GEN", start_time="2026-10-19 08:00:00"), _row("r2", "ST-GEN")],
			{"GENERAL": 2},
			[_bay("BAY-01", "GENERAL", 8)],
		)
		self.assertEqual(plan["row_bays"], {"r2": "BAY-01"})

	def test_started_row_keeps_main_bay_on_its_bay(self):
		plan = self.plan(
			[_row("r1", "ST-GEN", start_time="2026-10-19 08:00:00", service_bay="BAY-02"), _row("r2", "ST-PIT")],
			{"GENERAL": 5, "PIT": 1},
			[_bay("BAY-01", "GENERAL", 8), _bay("BAY-02", "GENERAL", 0), _bay("PIT-01", "PIT", 8)],
		)
		self.assertEqual(plan["service_bay"], "BAY-02")
		self.assertEqual(plan["row_bays"], {"r2": "PIT-01"})

	def test_rows_without_hours_still_get_a_bay(self):
		plan = self.plan([_row("r1", "ST-GEN")], {}, [_bay("BAY-01", "GENERAL", 8)])
		self.assertEqual(plan["service_bay"], "BAY-01")
		self.assertEqual(plan["row_bays"], {"r1": "BAY-01"})

	def test_no_active_bay_at_all_returns_nothing(self):
		plan = self.plan([_row("r1", "ST-GEN")], {"GENERAL": 2}, [])
		self.assertIsNone(plan["service_bay"])
		self.assertEqual(plan["row_bays"], {"r1": None})

# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.api.technician_portal import _validate_completion
from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	get_bay_warnings,
	select_requisition_rows,
)


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

		with patch("frappe.get_all", return_value=["SO-2026-00001"]):
			warnings = get_bay_warnings(so)

		self.assertEqual(len(warnings), 1)
		self.assertIn("BAY-1", warnings[0])
		self.assertIn("SO-2026-00001", warnings[0])

	def test_bay_warning_when_job_needs_pit_but_bay_has_none(self):
		"""งานที่ต้องใช้หลุมซ่อม แต่ช่องจอดที่จะได้ใช้จริงไม่มีหลุม → เตือน"""
		so = make_order(service_bay="BAY-1", labor_rows=[{"service_type": "ST-OIL"}])

		# get_all ถูกเรียก 3 ครั้ง: ใบงานที่ใช้ช่องจอดนี้, service type ที่ต้องใช้หลุม, ช่องจอดที่มีหลุม
		with patch("frappe.get_all", side_effect=[[], ["ST-OIL"], []]):
			warnings = get_bay_warnings(so)

		self.assertEqual(len(warnings), 1)
		self.assertIn("ST-OIL", warnings[0])
		self.assertIn("BAY-1", warnings[0])

	def test_no_bay_warning_when_pit_available(self):
		"""ช่องจอดว่างและมีหลุมครบตามที่งานต้องการ → ไม่มีคำเตือน"""
		so = make_order(service_bay="BAY-1", labor_rows=[{"service_type": "ST-OIL"}])

		with patch("frappe.get_all", side_effect=[[], ["ST-OIL"], ["BAY-1"]]):
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

# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""ฟิลด์ที่แอปเพิ่มบน doctype ของ ERPNext

ค่าพวกนี้อยู่ในฐานข้อมูลเป็น Custom Field ซึ่งแก้ด้วยมือผ่าน UI ได้ การประกาศไว้ใน
CUSTOM_FIELDS อย่างเดียวจึงไม่การันตีว่า site ใช้ค่านั้นจริง เทสต์นี้ตรวจของที่ใช้จริง
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.tests import IntegrationTestCase

from truck_service_center.install import CUSTOM_FIELDS
from truck_service_center.patches.show_service_order_columns_in_stock_entry_list import execute


class TestStockEntryCustomFields(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# idempotent และ update=True — ปรับฟิลด์เดิมให้ตรงกับที่ประกาศไว้
		create_custom_fields(CUSTOM_FIELDS)
		frappe.clear_cache(doctype="Stock Entry")

	def test_service_order_is_a_standard_filter(self):
		"""หน้ารายการ Stock Entry ต้องมีช่องกรองด้วยเลขใบสั่งงาน

		คำถามที่ถามบ่อยที่สุดคือ "ใบสั่งงานนี้เบิกอะไหล่ไปแล้วบ้าง" ถ้าไม่มีช่องนี้
		ต้องไปเพิ่มฟิลเตอร์เองทุกครั้ง
		"""
		field = frappe.get_meta("Stock Entry").get_field("custom_service_order")

		self.assertIsNotNone(field, "ไม่พบฟิลด์ custom_service_order บน Stock Entry")
		self.assertTrue(field.in_standard_filter, "custom_service_order ไม่ได้เป็น standard filter")

	def test_service_order_link_still_points_at_service_order(self):
		"""ช่องกรองต้องเป็น Link ไปยัง Service Order จะได้ค้นด้วย autocomplete ได้"""
		field = frappe.get_meta("Stock Entry").get_field("custom_service_order")

		self.assertEqual(field.fieldtype, "Link")
		self.assertEqual(field.options, "Service Order")

	def test_service_order_link_stays_read_only(self):
		"""ระบบเป็นคนเขียนค่านี้ (create_material_issue) ผู้ใช้ต้องแก้เองไม่ได้"""
		field = frappe.get_meta("Stock Entry").get_field("custom_service_order")

		self.assertTrue(field.read_only)

	def test_service_order_is_a_list_view_column(self):
		"""เลขใบสั่งงานต้องขึ้นเป็นคอลัมน์ในหน้ารายการ ไม่ต้องเปิดทีละใบเพื่อดู"""
		field = frappe.get_meta("Stock Entry").get_field("custom_service_order")

		self.assertTrue(field.in_list_view, "custom_service_order ไม่ได้อยู่ในคอลัมน์หน้ารายการ")

	def test_created_by_name_is_a_list_view_column(self):
		"""ผู้สร้างใบเบิกต้องขึ้นเป็นคอลัมน์ และเป็น Data (เก็บชื่อ ไม่ใช่ user id)"""
		field = frappe.get_meta("Stock Entry").get_field("custom_created_by_name")

		self.assertIsNotNone(field, "ไม่พบฟิลด์ custom_created_by_name บน Stock Entry")
		self.assertTrue(field.in_list_view)
		self.assertEqual(field.fieldtype, "Data")
		self.assertTrue(field.read_only)

	def test_superseded_owner_field_is_gone(self):
		"""ฟิลด์รอบก่อน (ผู้เปิดใบสั่งงาน) ต้องถูกลบ ไม่ค้างเป็นคอลัมน์ว่าง"""
		self.assertIsNone(frappe.get_meta("Stock Entry").get_field("custom_service_order_owner"))

	def test_filtering_by_service_order_returns_only_its_issues(self):
		"""กรองแล้วต้องได้เฉพาะใบเบิกของใบสั่งงานนั้น"""
		linked = frappe.get_all(
			"Stock Entry",
			filters={"custom_service_order": ["is", "set"]},
			pluck="custom_service_order",
			limit=1,
		)
		if not linked:
			self.skipTest("site นี้ยังไม่มีใบเบิกที่ผูกกับใบสั่งงาน")

		service_order = linked[0]
		rows = frappe.get_all(
			"Stock Entry",
			filters={"custom_service_order": service_order},
			fields=["custom_service_order"],
		)

		self.assertTrue(rows)
		self.assertEqual({row.custom_service_order for row in rows}, {service_order})


class TestStockEntryListColumns(IntegrationTestCase):
	"""layout ที่ผู้ใช้ pin ไว้ต้องได้คอลัมน์ใหม่ด้วย

	in_list_view ไม่มีผลเลยเมื่อ site มี List View Settings ของ doctype นั้น — ฝั่ง client
	ใช้ list_view_settings.fields แทน docfield ทั้งหมด และ record นั้นเกิดเองตั้งแต่มีคน
	ลากปรับความกว้างคอลัมน์
	"""

	SETTINGS = "Stock Entry"

	def _set_pinned_columns(self, fields):
		if frappe.db.exists("List View Settings", self.SETTINGS):
			doc = frappe.get_doc("List View Settings", self.SETTINGS)
		else:
			doc = frappe.new_doc("List View Settings")
			doc.name = self.SETTINGS
		doc.fields = frappe.as_json(fields)
		doc.save(ignore_permissions=True)
		return doc

	def _pinned_fieldnames(self):
		doc = frappe.get_doc("List View Settings", self.SETTINGS)
		return [row["fieldname"] for row in frappe.parse_json(doc.fields)]

	def test_patch_inserts_columns_after_stock_entry_type(self):
		"""คอลัมน์ใหม่ต้องอยู่ต่อจากประเภทใบเบิก ไม่ใช่ไปต่อท้ายสุดจนมองไม่เห็น"""
		self._set_pinned_columns(
			[
				{"fieldname": "stock_entry_type", "label": "Stock Entry Type"},
				{"fieldname": "purpose", "label": "Purpose"},
			]
		)

		execute()

		self.assertEqual(
			self._pinned_fieldnames(),
			["stock_entry_type", "custom_service_order", "custom_created_by_name", "purpose"],
		)

	def test_patch_is_idempotent(self):
		"""รันซ้ำ (ทุกครั้งที่ migrate) ต้องไม่เพิ่มคอลัมน์ซ้ำ"""
		self._set_pinned_columns([{"fieldname": "stock_entry_type", "label": "Stock Entry Type"}])

		execute()
		first = self._pinned_fieldnames()
		execute()

		self.assertEqual(self._pinned_fieldnames(), first)

	def test_patch_drops_the_superseded_column(self):
		"""คอลัมน์รอบก่อนต้องหายไป ไม่งั้นหน้ารายการจะมีช่องว่างที่ไม่มีฟิลด์รองรับ"""
		self._set_pinned_columns(
			[
				{"fieldname": "stock_entry_type", "label": "Stock Entry Type"},
				{"fieldname": "custom_service_order_owner", "label": "ผู้เปิดใบสั่งงาน"},
			]
		)

		execute()

		self.assertNotIn("custom_service_order_owner", self._pinned_fieldnames())

	def test_patch_orders_our_columns_together(self):
		"""คอลัมน์ของแอปต้องอยู่ติดกันตามลำดับที่ตั้งใจ ไม่ว่าเดิมจะเรียงยังไง"""
		self._set_pinned_columns(
			[
				{"fieldname": "stock_entry_type", "label": "Stock Entry Type"},
				{"fieldname": "custom_created_by_name", "label": "ผู้สร้างใบเบิก"},
				{"fieldname": "purpose", "label": "Purpose"},
				{"fieldname": "custom_service_order", "label": "ใบสั่งงาน"},
			]
		)

		execute()

		self.assertEqual(
			self._pinned_fieldnames(),
			["stock_entry_type", "custom_service_order", "custom_created_by_name", "purpose"],
		)

	def test_patch_keeps_user_widths_and_order(self):
		"""ความกว้าง/ลำดับที่ผู้ใช้ตั้งไว้ต้องไม่ถูกรื้อ"""
		self._set_pinned_columns(
			[
				{"fieldname": "stock_entry_type", "label": "Stock Entry Type"},
				{"fieldname": "name", "label": "ID", "width": 156.75},
			]
		)

		execute()

		doc = frappe.get_doc("List View Settings", self.SETTINGS)
		id_column = next(row for row in frappe.parse_json(doc.fields) if row["fieldname"] == "name")
		self.assertEqual(id_column["width"], 156.75)
		self.assertEqual(self._pinned_fieldnames()[-1], "name")

	def test_patch_is_a_noop_without_pinned_layout(self):
		"""site ที่ไม่มี layout ค้างไว้ ต้องปล่อยให้ in_list_view ทำงานเอง"""
		if frappe.db.exists("List View Settings", self.SETTINGS):
			frappe.delete_doc("List View Settings", self.SETTINGS, force=1, ignore_permissions=True)

		execute()  # ต้องไม่โยนและไม่สร้าง record ขึ้นมาเอง

		self.assertFalse(frappe.db.exists("List View Settings", self.SETTINGS))

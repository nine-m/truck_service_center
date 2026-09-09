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

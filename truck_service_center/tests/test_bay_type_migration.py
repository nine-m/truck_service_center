# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""การย้ายข้อมูลจากธง has_pit/requires_pit มาเป็น Bay Type

patch ตัวนี้รันทุกครั้งที่ migrate จนกว่าจะถูกทำเครื่องหมายว่ารันแล้ว และผู้ดูแลระบบ
สั่งรันซ้ำเองได้ด้วย bench execute จึงต้องพิสูจน์ว่ารันซ้ำแล้วไม่ทับค่าที่ผู้ใช้แก้เอง
นอกจากนั้นยังตรึงกฎ "ประเภทเริ่มต้นมีได้ตัวเดียว" ซึ่งทั้งระบบพึ่งเป็น fallback
"""

import frappe
from frappe.tests import IntegrationTestCase

from truck_service_center.patches.migrate_pit_to_bay_type import GENERAL, PIT
from truck_service_center.patches.migrate_pit_to_bay_type import execute as migrate_bay_types
from truck_service_center.truck_service_center.doctype.bay_type.bay_type import get_default_bay_type

TEST_BAY_TYPE_CODE = "ZZ-TEST-TYPE"


class TestBayTypeMigration(IntegrationTestCase):
	"""ใช้ข้อมูลจริงของ site (Bay Type ที่ seed ไว้) แต่แถวทดสอบขึ้นต้นด้วย ZZ-TEST-

	IntegrationTestCase rollback ให้ตอนจบ "ทั้งคลาส" ไม่ใช่รายเทสต์ แต่ละเทสต์จึงต้องใช้
	ชื่อช่องจอดของตัวเอง ไม่งั้นจะชนกันเองที่ autoname (field:bay_name)
	"""

	def make_legacy_bay(self, bay_name, has_pit=0):
		"""ช่องจอดที่ยังไม่มีประเภท — จำลองแถวเดิมที่สร้างไว้ก่อนมี Bay Type

		ต้องล้าง bay_type ด้วย SQL หลัง insert เพราะ controller เติมประเภทเริ่มต้นให้เสมอ
		"""
		bay = frappe.get_doc(
			{
				"doctype": "Service Bay",
				"bay_name": bay_name,
				"daily_capacity_hours": 8,
				"is_active": 1,
			}
		).insert()

		frappe.db.sql("update `tabService Bay` set bay_type = null where name = %s", bay.name)
		if has_pit and frappe.db.has_column("Service Bay", "has_pit"):
			frappe.db.sql("update `tabService Bay` set has_pit = 1 where name = %s", bay.name)

		return bay.name

	def test_legacy_bay_gets_a_bay_type(self):
		"""ช่องจอดที่ยังว่างต้องถูกเติมให้ครบ ไม่งั้นการจัดช่องจอดจะมองไม่เห็นช่องนั้น"""
		bay = self.make_legacy_bay("ZZ-TEST-BAY-LEGACY", has_pit=1)

		migrate_bay_types()

		# site ที่ trim คอลัมน์เก่าไปแล้วอ่านธงหลุมไม่ได้ ช่องนั้นจึงตกมาที่ประเภททั่วไป
		expected = PIT if frappe.db.has_column("Service Bay", "has_pit") else GENERAL
		self.assertEqual(frappe.db.get_value("Service Bay", bay, "bay_type"), expected)

	def test_rerun_does_not_touch_values(self):
		"""รันซ้ำต้องไม่ทับค่าที่ผู้ใช้แก้เอง — patch นี้เติมเฉพาะแถวที่ยังว่าง"""
		bay = self.make_legacy_bay("ZZ-TEST-BAY-RERUN", has_pit=1)

		migrate_bay_types()
		frappe.db.set_value("Service Bay", bay, "bay_type", GENERAL, update_modified=False)
		migrate_bay_types()

		self.assertEqual(frappe.db.get_value("Service Bay", bay, "bay_type"), GENERAL)

	def test_service_types_without_the_legacy_flag_stay_blank(self):
		"""งานที่ไม่ได้ต้องใช้หลุม ต้องถูกปล่อยว่างไว้ = ตามประเภทเริ่มต้นของระบบ

		ถ้าเขียน GENERAL ลงไปทุกแถว ศูนย์ที่เปลี่ยนประเภทเริ่มต้นทีหลังจะต้องไล่แก้เอง
		"""
		migrate_bay_types()

		blank = frappe.db.count("Service Type", {"bay_type": ["in", [None, ""]]})
		self.assertGreater(blank, 0, "ทุก Service Type ถูกเขียนประเภทลงไปหมด ซึ่งไม่ใช่พฤติกรรมที่ตั้งใจ")

	def test_new_bay_falls_back_to_the_default_type(self):
		"""สร้างช่องจอดโดยไม่กรอกประเภท → ได้ประเภทเริ่มต้นอัตโนมัติ (reqd แต่ไม่ต้องกรอกเอง)"""
		bay = frappe.get_doc(
			{
				"doctype": "Service Bay",
				"bay_name": "ZZ-TEST-BAY-DEFAULT",
				"daily_capacity_hours": 8,
				"is_active": 1,
			}
		).insert()

		self.assertEqual(bay.bay_type, get_default_bay_type())

	def test_setting_a_new_default_clears_the_old_one(self):
		"""ประเภทเริ่มต้นมีได้ตัวเดียว — ตัวเก่าต้องถูกปลดธงให้เอง ไม่ต้องให้ผู้ใช้ไปปลดก่อน"""
		previous = get_default_bay_type()
		self.assertIsNotNone(previous, "site นี้ยังไม่มีประเภทช่องจอดเริ่มต้น")

		frappe.get_doc(
			{
				"doctype": "Bay Type",
				"bay_type_code": TEST_BAY_TYPE_CODE,
				"bay_type_name": "ประเภททดสอบ",
				"is_default": 1,
				"is_active": 1,
			}
		).insert()

		self.assertEqual(frappe.db.get_value("Bay Type", previous, "is_default"), 0)
		self.assertEqual(get_default_bay_type(), TEST_BAY_TYPE_CODE)

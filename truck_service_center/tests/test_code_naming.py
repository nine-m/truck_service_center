# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""ชื่อเอกสารต้องตรงกับรหัสที่ถูกปรับแล้ว — doctype ที่ autoname = field:<รหัส>

Frappe ตั้งชื่อเอกสาร (set_new_name) ก่อน validate ถ้าปรับรหัส (ตัดช่องว่าง/ตัวใหญ่) แค่ใน validate
พิมพ์ " pit " จะได้เอกสารชื่อ "pit" แต่รหัส "PIT" — Link ที่อ้าง "PIT" ในโค้ด/patch หาไม่เจอ
เรียก set_new_name ตรง ๆ กับเอกสารที่ไม่ได้บันทึก จึงไม่ต้อง insert อะไรลงฐานข้อมูล
"""

import frappe
from frappe.model.naming import set_new_name
from frappe.tests import UnitTestCase

CASES = (
	# doctype, ฟิลด์รหัส, ค่าที่พิมพ์, ชื่อที่ควรได้
	("Bay Type", "bay_type_code", " pit ", "PIT"),
	("PM Group", "pm_group_code", " pm1 ", "PM1"),
	("Service Type Group", "group_code", " eng ", "ENG"),
	("Service Branch", "branch_code", " bkk ", "BKK"),
	("Repair Position", "position_code", " fl ", "FL"),
	# รหัสรุ่นรถเป็นตัวพิมพ์ผสมโดยเจตนา (Hino500) — ตัดช่องว่างอย่างเดียว
	("PM Truck Type", "pm_truck_type_code", " Hino500 ", "Hino500"),
)


class TestCodeNaming(UnitTestCase):
	def test_name_matches_normalized_code(self):
		for doctype, fieldname, typed, expected in CASES:
			with self.subTest(doctype=doctype):
				doc = frappe.new_doc(doctype)
				doc.set(fieldname, typed)
				set_new_name(doc)
				self.assertEqual(doc.name, expected)
				self.assertEqual(doc.get(fieldname), expected)

# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase


def make_group(*users):
	"""กลุ่มบริการในหน่วยความจำ (ไม่ insert) พร้อมรายชื่อผู้อนุมัติ"""
	group = frappe.new_doc("Service Type Group")
	group.group_code = "ENG"
	group.group_name = "เครื่องยนต์"
	for user in users:
		group.append("supervisors", {"user": user})
	return group


def roles_of(mapping):
	"""แทน frappe.get_roles ตาม user — user ที่ไม่ได้ระบุถือว่าไม่มี role"""
	return lambda user=None: mapping.get(user, [])


class UnitTestServiceTypeGroup(UnitTestCase):
	def test_supervisor_role_is_accepted(self):
		"""ผู้มี role Technician Supervisor ตั้งเป็นผู้อนุมัติได้"""
		group = make_group("sup@example.com")

		with patch("frappe.get_roles", side_effect=roles_of({"sup@example.com": ["Technician Supervisor"]})):
			group.validate_supervisors()

	def test_manager_roles_are_accepted(self):
		"""หัวหน้าช่าง/ผู้จัดการอนุมัติได้ทุกกลุ่มอยู่แล้ว จะใส่ชื่อในกลุ่มด้วยก็ได้"""
		group = make_group("boss@example.com")

		with patch("frappe.get_roles", side_effect=roles_of({"boss@example.com": ["Technician Manager"]})):
			group.validate_supervisors()

	def test_plain_technician_is_rejected(self):
		"""ช่างธรรมดาเป็นผู้อนุมัติไม่ได้ — กันตั้งผิดคนโดยไม่ตั้งใจ"""
		group = make_group("tech@example.com")

		with (
			patch("frappe.get_roles", side_effect=roles_of({"tech@example.com": ["Technician"]})),
			self.assertRaises(frappe.ValidationError),
		):
			group.validate_supervisors()

	def test_duplicate_supervisor_is_rejected(self):
		"""ชื่อซ้ำในตารางไม่มีประโยชน์และทำให้รายการผู้อนุมัติดูสับสน"""
		group = make_group("sup@example.com", "sup@example.com")

		with (
			patch("frappe.get_roles", side_effect=roles_of({"sup@example.com": ["Technician Supervisor"]})),
			self.assertRaises(frappe.ValidationError),
		):
			group.validate_supervisors()

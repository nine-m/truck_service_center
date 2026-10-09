# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# role ที่ถูกตั้งเป็นผู้อนุมัติใบเบิกอะไหล่ของกลุ่มได้ (Service Type Group.supervisors)
SUPERVISOR_ROLE = "Technician Supervisor"

# role ที่อนุมัติใบเบิกได้ทุกกลุ่มโดยไม่ต้องอยู่ในรายชื่อ — และเป็นผู้อนุมัติของใบที่ไม่มีกลุ่ม
# หรือกลุ่มที่ยังไม่ได้ตั้งหัวหน้างาน (ไม่งั้นใบพวกนั้นจะค้างรออนุมัติตลอดไป)
APPROVER_FALLBACK_ROLES = {"Technician Manager", "Service Manager", "System Manager"}


class ServiceTypeGroup(Document):
	def validate(self):
		"""ตรวจสอบความถูกต้องของข้อมูล"""
		self.validate_group_code()
		self.validate_supervisors()

	def validate_group_code(self):
		"""ตรวจสอบรูปแบบรหัสกลุ่ม"""
		if self.group_code:
			self.group_code = self.group_code.upper()

	def validate_supervisors(self):
		"""ผู้อนุมัติใบเบิกต้องไม่ซ้ำ และต้องมี role ที่อนุมัติได้จริง

		กันตั้งช่างธรรมดาเป็นผู้อนุมัติโดยไม่ตั้งใจ — role เป็นตัวบอกว่าองค์กรมอบอำนาจนี้ให้แล้ว
		"""
		seen = set()
		allowed_roles = APPROVER_FALLBACK_ROLES | {SUPERVISOR_ROLE}

		for row in self.get("supervisors") or []:
			if not row.user:
				continue

			if row.user in seen:
				frappe.throw(_("ผู้อนุมัติ {0} ซ้ำกันในแถวที่ {1}").format(row.full_name or row.user, row.idx))
			seen.add(row.user)

			if not allowed_roles & set(frappe.get_roles(row.user)):
				frappe.throw(
					_("{0} ไม่มี role {1} จึงตั้งเป็นผู้อนุมัติใบเบิกไม่ได้").format(
						row.full_name or row.user, SUPERVISOR_ROLE
					)
				)


@frappe.whitelist()
def get_active_groups():
	"""ดึงรายการกลุ่มบริการที่เปิดใช้งาน"""
	groups = frappe.get_all(
		"Service Type Group",
		filters={"is_active": 1},
		fields=["name", "group_code", "group_name"],
		order_by="group_code",
	)
	return groups

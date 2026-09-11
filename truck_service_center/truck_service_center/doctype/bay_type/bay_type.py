# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BayType(Document):
	def validate(self):
		self.validate_code()
		self.validate_single_default()

	def validate_code(self):
		"""รหัสประเภทเป็น autoname (field:bay_type_code) — ช่องว่างล้วนจะได้ชื่อเอกสารเพี้ยน

		บังคับตัวพิมพ์ใหญ่แบบเดียวกับ ServiceTypeGroup.validate_group_code เพื่อให้ patch
		และเทสต์อ้างรหัส "PIT" ได้ตรง ๆ ไม่ว่าผู้ใช้จะพิมพ์มาแบบไหน
		"""
		self.bay_type_code = (self.bay_type_code or "").strip().upper()
		if not self.bay_type_code:
			frappe.throw("กรุณาระบุรหัสประเภทช่องจอด")

	def validate_single_default(self):
		"""ประเภทเริ่มต้นมีได้ตัวเดียว — ตั้งตัวใหม่แล้วปลดธงตัวเก่าให้เอง

		last-write-wins อ่อนโยนกว่าการ throw ซึ่งบังคับให้ผู้ใช้ไปปลดธงตัวเก่าเองก่อน
		แต่ประเภทที่ปิดใช้งานอยู่เป็นค่าเริ่มต้นไม่ได้ เพราะ get_default_bay_type กรอง
		is_active ทิ้ง ระบบจะกลายเป็นไม่มีค่าเริ่มต้นทั้งที่ฟอร์มบอกว่ามี
		"""
		if not self.is_default:
			return

		if not self.is_active:
			frappe.throw("ประเภทช่องจอดที่ปิดใช้งานอยู่ ตั้งเป็นประเภทเริ่มต้นไม่ได้")

		for name in frappe.get_all("Bay Type", filters={"is_default": 1}, pluck="name"):
			if name == self.name:
				continue
			frappe.db.set_value("Bay Type", name, "is_default", 0, update_modified=False)

	def on_trash(self):
		"""ทั้งระบบใช้ประเภทเริ่มต้นเป็นตัวรับงานที่ไม่ระบุประเภท ลบทิ้งเฉย ๆ ไม่ได้"""
		if self.is_default:
			frappe.throw("ลบประเภทช่องจอดเริ่มต้นไม่ได้ — ตั้งประเภทอื่นเป็นค่าเริ่มต้นก่อน")


def get_default_bay_type():
	"""ประเภทช่องจอดเริ่มต้นของระบบ — ใช้กับงานที่ไม่ได้ระบุประเภทไว้

	คืน None ได้ (site ที่ยังไม่ได้ seed หรือปลดธงทิ้ง) ผู้เรียกทุกคนต้องรับมือกรณีนี้เอง
	"""
	return frappe.db.get_value("Bay Type", {"is_default": 1, "is_active": 1}, "name")


@frappe.whitelist()
def get_active_bay_types():
	"""ประเภทช่องจอดที่เปิดใช้งาน — ตามแบบ get_active_bays / get_active_groups"""
	return frappe.get_all(
		"Bay Type",
		filters={"is_active": 1},
		fields=["name", "bay_type_code", "bay_type_name", "is_default"],
		order_by="bay_type_name asc",
	)

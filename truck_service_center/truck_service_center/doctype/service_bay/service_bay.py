# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from truck_service_center.truck_service_center.doctype.bay_type.bay_type import get_default_bay_type


class ServiceBay(Document):
	def validate(self):
		self.validate_name_not_blank()
		self.apply_default_bay_type()

	def validate_name_not_blank(self):
		"""ชื่อช่องจอดเป็น autoname (field:bay_name) — ช่องว่างล้วนจะได้ชื่อเอกสารเพี้ยน"""
		self.bay_name = (self.bay_name or "").strip()
		if not self.bay_name:
			frappe.throw("กรุณาระบุชื่อช่องจอดซ่อม")

	def apply_default_bay_type(self):
		"""ไม่ระบุประเภท → ใช้ประเภทเริ่มต้นของระบบ

		bay_type เป็น reqd ในไฟล์ JSON แต่ยังเติมให้ตรงนี้ได้ เพราะ Frappe รัน validate()
		ก่อน _validate_mandatory() เสมอ ค่าที่เติมจึงทันการตรวจฟิลด์บังคับพอดี

		site ที่ยังไม่มี Bay Type เลยจะติด mandatory error เปล่า ๆ ที่อ่านไม่รู้เรื่อง
		จึงบอกตรง ๆ ว่าต้องไปสร้าง master ก่อน
		"""
		if self.bay_type:
			return

		self.bay_type = get_default_bay_type()
		if not self.bay_type:
			frappe.throw("ยังไม่มีประเภทช่องจอด — สร้าง Bay Type อย่างน้อยหนึ่งรายการก่อน")


@frappe.whitelist()
def get_active_bays():
	"""ช่องจอดที่เปิดใช้งาน — ใช้ทั้งพอร์ทัลช่างและหน้า desk"""
	return frappe.get_all(
		"Service Bay",
		filters={"is_active": 1},
		fields=["name", "bay_name", "bay_type"],
		order_by="bay_name asc",
	)

# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class BayCapacityOverride(Document):
	def validate(self):
		self.validate_capacity_hours()
		self.validate_no_duplicate()

	def validate_capacity_hours(self):
		"""ชั่วโมงรับงานติดลบไม่มีความหมาย — 0 คือปิดทำการอยู่แล้ว"""
		if flt(self.capacity_hours) < 0:
			frappe.throw("ชั่วโมงรับงานต้องไม่ติดลบ (0 = ปิดทำการ)")

	def validate_no_duplicate(self):
		"""วันเดียวกัน + ช่องจอดเดียวกัน ต้องมีได้ใบเดียว

		รวมถึงคู่ที่เว้นช่องจอดว่าง (มีผลทุกช่องจอด) ซึ่งต้องมีได้ใบเดียวต่อวันเช่นกัน
		มิฉะนั้นลำดับความสำคัญของ cap จะขึ้นกับลำดับแถวที่ query คืนมา
		"""
		if not self.override_date:
			return

		filters = {
			"override_date": self.override_date,
			"name": ["!=", self.name or ""],
		}
		filters["service_bay"] = self.service_bay or ["in", [None, ""]]

		existing = frappe.get_all("Bay Capacity Override", filters=filters, pluck="name", limit=1)
		if existing:
			scope = f"ช่องจอด {self.service_bay}" if self.service_bay else "ทุกช่องจอด"
			frappe.throw(f"มีรายการปรับชั่วโมงรับงานของวันที่ {self.override_date} ({scope}) อยู่แล้ว: {existing[0]}")

# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document

# คลัง/ศูนย์ต้นทุนของสาขา — ต้องเป็นของ Company เดียวกับระบบ (ทุกสาขาอยู่ใต้ Company เดียว)
COMPANY_LINK_FIELDS = {
	"default_source_warehouse": "Warehouse",
	"default_warehouse": "Warehouse",
	"default_cost_center": "Cost Center",
	"labor_cost_center": "Cost Center",
}


class ServiceBranch(Document):
	def validate(self):
		self.branch_code = (self.branch_code or "").strip().upper()
		if not re.fullmatch(r"[A-Z0-9]+", self.branch_code):
			frappe.throw("รหัสสาขาต้องเป็นตัวอักษรอังกฤษหรือตัวเลขเท่านั้น (ไม่มีช่องว่างหรือขีด)")

		self.document_prefix = (self.document_prefix or "").strip().upper() or None
		if self.document_prefix and not re.fullmatch(r"[A-Z0-9]+", self.document_prefix):
			frappe.throw("รหัสนำหน้าเลขเอกสารต้องเป็นตัวอักษรอังกฤษหรือตัวเลขเท่านั้น")

		if self.tax_branch_code:
			self.tax_branch_code = self.tax_branch_code.strip()
			if not re.fullmatch(r"\d{5}", self.tax_branch_code):
				frappe.throw("เลขที่สาขา (ภาษี) ต้องเป็นตัวเลข 5 หลัก เช่น 00000 หรือ 00002")

		self.validate_company_links()
		self.validate_unique_prefix()

	def validate_company_links(self):
		company = frappe.db.get_single_value("Truck Service Center Settings", "default_company")
		if not company:
			return
		for fieldname, doctype in COMPANY_LINK_FIELDS.items():
			value = self.get(fieldname)
			if value and frappe.db.get_value(doctype, value, "company") != company:
				frappe.throw(f"{self.meta.get_label(fieldname)} '{value}' ไม่ได้เป็นของบริษัท {company}")

	def validate_unique_prefix(self):
		"""สองสาขาใช้รหัสนำหน้าเดียวกันไม่ได้ ไม่งั้นเลขเอกสารสองสาขาจะรันชุดเดียวกัน
		(เว้นว่างได้สาขาเดียวในทางปฏิบัติ แต่ไม่บังคับ — สาขาที่เว้นว่างจะใช้ชุดเลขกลางร่วมกัน)"""
		if not self.document_prefix:
			return
		other = frappe.db.get_value(
			"Service Branch", {"document_prefix": self.document_prefix, "name": ["!=", self.name]}
		)
		if other:
			frappe.throw(f"รหัสนำหน้าเลขเอกสาร {self.document_prefix} ถูกใช้แล้วโดยสาขา {other}")

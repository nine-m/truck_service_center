# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class TruckServiceCenterSettings(Document):
	def validate(self):
		# แสดงคำเตือนถ้ายังไม่ได้ตั้งค่า Labor Item
		if not self.labor_item:
			frappe.msgprint(
				"แนะนำให้ตั้งค่า 'รายการสินค้าสำหรับค่าแรง' เพื่อให้สามารถสร้าง Sales Invoice ที่มีค่าแรงได้",
				indicator="orange",
				title="คำแนะนำ",
			)

		# ตรวจสอบความสอดคล้องของเทมเพลตภาษี
		self.validate_tax_templates()

	def validate_tax_templates(self):
		"""ตรวจสอบว่าเทมเพลตภาษีตั้งค่าถูกต้องตามประเภท"""
		if self.vat_exclusive_template:
			self._validate_template_type(
				self.vat_exclusive_template, expected_inclusive=False, label="ราคาแยก VAT"
			)

		if self.vat_inclusive_template:
			self._validate_template_type(
				self.vat_inclusive_template, expected_inclusive=True, label="ราคารวม VAT"
			)

		# แจ้งเตือนถ้ายังไม่ได้ตั้งค่าเทมเพลต
		if self.default_tax_type == "ราคาแยก VAT" and not self.vat_exclusive_template:
			frappe.msgprint(
				"แนะนำให้ตั้งค่า 'เทมเพลต ราคาแยก VAT' เพื่อให้ Sales Invoice ใช้เทมเพลตภาษีอัตโนมัติ",
				indicator="orange",
				title="คำแนะนำ",
			)
		elif self.default_tax_type == "ราคารวม VAT" and not self.vat_inclusive_template:
			frappe.msgprint(
				"แนะนำให้ตั้งค่า 'เทมเพลต ราคารวม VAT' เพื่อให้ Sales Invoice ใช้เทมเพลตภาษีอัตโนมัติ",
				indicator="orange",
				title="คำแนะนำ",
			)

	def _validate_template_type(self, template_name, expected_inclusive, label):
		"""ตรวจสอบว่าเทมเพลตมี included_in_print_rate ตรงกับประเภทที่คาดหวัง"""
		taxes = frappe.get_all(
			"Sales Taxes and Charges",
			filters={"parent": template_name, "parenttype": "Sales Taxes and Charges Template"},
			fields=["included_in_print_rate", "rate", "charge_type"],
			order_by="idx",
		)

		if not taxes:
			frappe.msgprint(
				f"เทมเพลต '{template_name}' สำหรับ {label} ไม่มีรายการภาษี กรุณาตรวจสอบ",
				indicator="orange",
				title="ตรวจสอบเทมเพลตภาษี",
			)
			return

		for tax in taxes:
			if tax.included_in_print_rate != expected_inclusive:
				expected_text = (
					"รวมในราคา (included_in_print_rate = Yes)"
					if expected_inclusive
					else "ไม่รวมในราคา (included_in_print_rate = No)"
				)
				frappe.msgprint(
					f"เทมเพลต '{template_name}' สำหรับ {label}: ควรตั้งค่าภาษีเป็น {expected_text}",
					indicator="orange",
					title="ตรวจสอบเทมเพลตภาษี",
				)
				break

	def get_tax_template_for_type(self, tax_type):
		"""คืนค่า Sales Taxes and Charges Template ตามประเภทภาษี"""
		if tax_type == "ราคาแยก VAT":
			return self.vat_exclusive_template
		elif tax_type == "ราคารวม VAT":
			return self.vat_inclusive_template
		return None


@frappe.whitelist()
def create_labor_item():
	"""สร้าง Labor Item อัตโนมัติ"""
	frappe.has_permission("Truck Service Center Settings", "write", throw=True)
	# ตรวจสอบว่ามีอยู่แล้วหรือไม่
	existing = frappe.db.exists("Item", {"item_name": "Labor Charge"})
	if existing:
		return existing

	# สร้าง Item ใหม่
	item = frappe.new_doc("Item")
	item.item_code = "LABOR-001"
	item.item_name = "Labor Charge"
	item.item_group = "Services"
	item.stock_uom = "Nos"
	item.is_stock_item = 0
	item.is_sales_item = 1
	item.is_service_item = 1
	item.description = "Labor charges for vehicle service"

	try:
		item.insert()
		frappe.db.commit()
		return item.name
	except Exception as e:
		frappe.log_error(f"Error creating labor item: {e!s}")
		frappe.throw(f"ไม่สามารถสร้าง Labor Item ได้: {e!s}")

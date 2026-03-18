# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ServiceType(Document):
	def on_update(self):
		"""อัปเดต labor_rate จาก item price list เมื่อเลือก item_code"""
		pass

	def validate(self):
		"""ตรวจสอบข้อมูลและดึงราคาจาก item หากมี"""
		# คำนวณยอดรวมสำหรับรายการอะไหล่
		self.calculate_item_amounts()
		
		# ดึงราคาเฉพาะเมื่อ item_code ถูกเปลี่ยนแปลง
		if self.has_value_changed('item_code'):
			self.set_labor_rate_from_item()

	def calculate_item_amounts(self):
		"""คำนวณยอดรวมสำหรับแต่ละรายการอะไหล่ และดึงราคาจาก Price List -> Standard Rate -> Value Rate"""
		from frappe.utils import flt

		for item in self.items:
			if item.item_code and not flt(item.rate):
				result = get_item_price(item.item_code)
				if result and result.get("price"):
					item.rate = flt(result["price"])
			item.amount = (item.qty or 0) * (item.rate or 0)

	def set_labor_rate_from_item(self):
		"""ดึงราคาจาก Price List ก่อน แล้ว fallback ไป Item"""
		if not self.item_code:
			return

		from frappe.utils import flt

		result = get_item_price(self.item_code)
		if result and result.get("price"):
			self.labor_rate = flt(result["price"])


@frappe.whitelist()
def get_item_price(item_code):
	"""ดึงราคาสินค้า โดยเช็คจาก Price List ก่อน แล้ว fallback ไป standard_rate"""
	from frappe.utils import flt

	if not item_code or not frappe.db.exists("Item", item_code):
		return {"price": None}

	price = 0

	# 1. ดึงจาก Item Price (Selling) ก่อน
	price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list") or "Standard Selling"

	item_price = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "selling": 1},
		"price_list_rate",
	)

	if item_price:
		price = flt(item_price)
	else:
		# 2. Fallback ไป standard_rate / valuation_rate
		item_data = frappe.db.get_value(
			"Item", item_code, ["standard_rate", "valuation_rate"], as_dict=True
		)
		if item_data:
			price = flt(item_data.standard_rate) or flt(item_data.valuation_rate)

	return {"price": price or None}


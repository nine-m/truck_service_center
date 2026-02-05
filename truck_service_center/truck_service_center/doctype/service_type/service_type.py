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
		# ดึงราคาเฉพาะเมื่อ item_code ถูกเปลี่ยนแปลง
		if self.has_value_changed('item_code'):
			self.set_labor_rate_from_item()

	def set_labor_rate_from_item(self):
		"""ดึงราคาจาก Item และ Price List"""
		item = frappe.get_doc('Item', self.item_code)
		
		if not item:
			return
		
		# ดึงราคา standard selling price จาก Item
		if hasattr(item, 'standard_rate') and item.standard_rate:
			self.labor_rate = item.standard_rate
		elif hasattr(item, 'valuation_rate') and item.valuation_rate:
			self.labor_rate = item.valuation_rate
		else:
			# ค้นหา Price List Entry สำหรับ item นี้
			price_list_entry = frappe.db.get_value(
				'Item Price',
				filters={
					'item_code': self.item_code,
					'selling': 1
				},
				fieldname='price_list_rate'
			)
			
			if price_list_entry:
				self.labor_rate = price_list_entry


@frappe.whitelist()
def get_item_price(item_code):
	"""ดึงราคาสินค้า"""
	try:
		item = frappe.get_doc('Item', item_code)
		
		if not item:
			return {'price': None}
		
		price = None
		
		# ลองดึงราคา standard rate ก่อน
		if hasattr(item, 'standard_rate') and item.standard_rate:
			price = item.standard_rate
		elif hasattr(item, 'valuation_rate') and item.valuation_rate:
			price = item.valuation_rate
		else:
			# ค้นหา Price List Entry
			price_entry = frappe.db.get_value(
				'Item Price',
				filters={
					'item_code': item_code,
					'selling': 1
				},
				fieldname='price_list_rate'
			)
			if price_entry:
				price = price_entry
		
		return {'price': price}
	
	except frappe.DoesNotExistError:
		frappe.log_error('Item not found: ' + item_code, 'Service Type')
		return {'price': None}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), 'Service Type - Get Item Price')
		return {'price': None}


# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class ServicePackage(Document):
	def validate(self):
		self.validate_package_items()
		self.calculate_totals()
	
	def validate_package_items(self):
		"""ตรวจสอบว่ามีรายการบริการในแพ็คเกจ"""
		if not self.package_items:
			frappe.throw("กรุณาเพิ่มรายการบริการในแพ็คเกจอย่างน้อย 1 รายการ")
	
	def calculate_totals(self):
		"""คำนวณยอดรวมและราคาแพ็คเกจ"""
		total_standard = 0
		
		# คำนวณยอดรวมมาตรฐาน
		for item in self.package_items:
			item.amount = flt(item.qty) * flt(item.rate)
			total_standard += item.amount
		
		self.total_standard_rate = total_standard
		
		# คำนวณราคาแพ็คเกจหลังหักส่วนลด
		if self.discount_percent:
			discount_amount = total_standard * flt(self.discount_percent) / 100
			self.package_rate = total_standard - discount_amount
		elif not self.package_rate:
			self.package_rate = total_standard
	
	def get_package_items_for_service_order(self):
		"""ดึงรายการบริการในแพ็คเกจเพื่อใช้ใน Service Order"""
		items = []
		for item in self.package_items:
			items.append({
				"item_code": item.item_code,
				"item_name": item.item_name,
				"qty": item.qty,
				"rate": item.rate,
				"amount": item.amount,
				"description": item.description or ""
			})
		return items
	
	def get_discount_amount(self):
		"""คำนวณจำนวนเงินส่วนลด"""
		if self.discount_percent and self.total_standard_rate:
			return flt(self.total_standard_rate) * flt(self.discount_percent) / 100
		return 0


@frappe.whitelist()
def get_package_details(package_name):
	"""ดึงข้อมูลแพ็คเกจพร้อมรายการบริการ"""
	if not package_name:
		return {}
	
	package = frappe.get_doc("Service Package", package_name)
	
	if not package.is_active:
		frappe.throw(f"แพ็คเกจ {package_name} ถูกปิดการใช้งานแล้ว")
	
	return {
		"package_name": package.package_name,
		"package_type": package.package_type,
		"package_rate": package.package_rate,
		"total_standard_rate": package.total_standard_rate,
		"discount_percent": package.discount_percent,
		"discount_amount": package.get_discount_amount(),
		"validity_days": package.validity_days,
		"service_interval_km": package.service_interval_km,
		"max_services": package.max_services,
		"description": package.description,
		"items": package.get_package_items_for_service_order()
	}


@frappe.whitelist()
def get_active_packages():
	"""ดึงรายการแพ็คเกจที่เปิดใช้งาน"""
	packages = frappe.get_all(
		"Service Package",
		filters={"is_active": 1},
		fields=["name", "package_name", "package_type", "package_rate", "description"],
		order_by="package_type, package_rate"
	)
	return packages

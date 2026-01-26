# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class ServicePackage(Document):
	def validate(self):
		self.validate_package_items()
		self.calculate_totals()
		self.validate_pricing()
	
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
		
		# คำนวณส่วนลดและราคาแพ็คเกจ
		# ถ้ามีการระบุราคาแพ็คเกจมา ให้คำนวณส่วนลดกลับ
		if self.package_rate and total_standard > 0:
			discount_amount = total_standard - flt(self.package_rate)
			self.discount_percent = (discount_amount / total_standard) * 100
		# ถ้ามีการระบุส่วนลด ให้คำนวณราคาแพ็คเกจ
		elif self.discount_percent:
			discount_amount = total_standard * flt(self.discount_percent) / 100
			self.package_rate = total_standard - discount_amount
		# ถ้าไม่มีทั้งสองอย่าง ให้ราคาแพ็คเกจเท่ากับราคามาตรฐาน
		elif not self.package_rate:
			self.package_rate = total_standard
			self.discount_percent = 0
	
	def validate_pricing(self):
		"""ตรวจสอบความถูกต้องของราคาและส่วนลด"""
		# ตรวจสอบส่วนลด
		if flt(self.discount_percent) < 0:
			frappe.throw("ส่วนลดต้องเป็นค่าบวก")
		
		if flt(self.discount_percent) > 100:
			frappe.throw("ส่วนลดไม่สามารถเกิน 100% ได้")
		
		# ตรวจสอบราคาแพ็คเกจ
		if flt(self.package_rate) < 0:
			frappe.throw("ราคาแพ็คเกจต้องเป็นค่าบวก")
		
		if flt(self.package_rate) > flt(self.total_standard_rate):
			frappe.msgprint(
				msg="ราคาแพ็คเกจสูงกว่าราคามาตรฐานรวม",
				title="คำเตือน",
				indicator="orange"
			)
		
		# ตรวจสอบความสอดคล้องระหว่างราคาแพ็คเกจและส่วนลด
		if self.total_standard_rate > 0:
			calculated_rate = flt(self.total_standard_rate) * (1 - flt(self.discount_percent) / 100)
			rate_difference = abs(flt(self.package_rate) - calculated_rate)
			
			# ให้ความคลาดเคลื่อนไม่เกิน 0.01 (เพื่อรองรับการปัดเศษ)
			if rate_difference > 0.01:
				frappe.throw(
					f"ราคาแพ็คเกจไม่สอดคล้องกับส่วนลด<br>"
					f"ราคามาตรฐาน: {self.total_standard_rate:.2f}<br>"
					f"ส่วนลด: {self.discount_percent:.2f}%<br>"
					f"ราคาแพ็คเกจที่คำนวณได้: {calculated_rate:.2f}<br>"
					f"ราคาแพ็คเกจที่ระบุ: {self.package_rate:.2f}"
				)
	
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

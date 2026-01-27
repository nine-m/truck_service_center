# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class ServiceOrder(Document):
	def validate(self):
		self.apply_service_package()
		self.calculate_totals()
		self.update_payment_status()
	
	def apply_service_package(self):
		"""นำรายการบริการจากแพ็คเกจมาใส่ใน service_items"""
		if self.service_package and not self.service_items:
			package_details = frappe.get_doc("Service Package", self.service_package)
			
			if not package_details.is_active:
				frappe.throw(f"แพ็คเกจ {self.service_package} ถูกปิดการใช้งานแล้ว")
			
			# เพิ่มรายการจากแพ็คเกจ
			for item in package_details.package_items:
				self.append("service_items", {
					"item_code": item.item_code,
					"qty": item.qty,
					"rate": item.rate,
					"warehouse": frappe.db.get_single_value("Stock Settings", "default_warehouse")
				})
			
			# ใช้ราคาแพ็คเกจ
			if package_details.discount_percent:
				self.discount_amount = package_details.get_discount_amount()
	
	def calculate_totals(self):
		"""คำนวณยอดรวมทั้งหมด"""
		# คำนวณยอดรวมอะไหล่
		self.total_parts_amount = 0
		for item in self.service_items:
			item.amount = flt(item.qty) * flt(item.rate)
			self.total_parts_amount += item.amount
		
		# คำนวณค่าแรงรวมและเวลารวมจากประเภทบริการทั้งหมด
		self.labor_charges = 0
		self.estimated_time = 0
		for service_type in self.service_types:
			self.labor_charges += flt(service_type.labor_charges)
			self.estimated_time += flt(service_type.estimated_time)
		
		# คำนวณยอดรวมทั้งหมด
		subtotal = flt(self.total_parts_amount) + flt(self.labor_charges)
		total = subtotal - flt(self.discount_amount) + flt(self.tax_amount)
		self.total_amount = total
		
		# คำนวณยอดคงค้าง
		self.outstanding_amount = flt(self.total_amount) - flt(self.paid_amount)
	
	def update_payment_status(self):
		"""อัพเดทสถานะการชำระเงิน"""
		if flt(self.paid_amount) == 0:
			self.payment_status = "Unpaid"
		elif flt(self.paid_amount) >= flt(self.total_amount):
			self.payment_status = "Paid"
		else:
			self.payment_status = "Partially Paid"
	
	def on_submit(self):
		"""เมื่อ submit ให้สร้าง Stock Entry และอัพเดทข้อมูลรถ"""
		self.create_stock_entry()
		self.update_vehicle_info()
    
	def before_submit(self):
		"""ก่อน submit ให้ตรวจสอบเงื่อนไขและตั้งสถานะเป็น Completed"""
		# 1. ต้องมีการสร้าง service type อย่างน้อย 1 รายการ
		if not self.service_types:
			frappe.throw("กรุณาเพิ่มประเภทบริการอย่างน้อย 1 รายการก่อน Submit")
		
		# 2. ราคายอดรวมทั้งหมดต้องมากกว่า 0
		if flt(self.total_amount) <= 0:
			frappe.throw("ยอดรวมทั้งหมดต้องมากกว่า 0")
		
		# 3. เวลาทำงานจริงต้องมากกว่า 0
		if flt(self.actual_time) <= 0:
			frappe.throw("กรุณาระบุเวลาทำงานจริงที่มากกว่า 0")
		
		self.status = "Completed"
	
	def create_stock_entry(self):
		"""สร้าง Stock Entry เพื่อตัดสต็อกอะไหล่"""
		if not self.service_items:
			return

		settings = frappe.get_single("Truck Service Center Settings")

		# ถ้าไม่เลือกให้สร้างอัตโนมัติ ให้ข้าม
		if settings.auto_create_stock_entry is False:
			return

		stock_entry = frappe.new_doc("Stock Entry")
		stock_entry.stock_entry_type = "Material Issue"
		stock_entry.company = settings.default_company or frappe.defaults.get_defaults().company
		stock_entry.set_posting_time = 1
		stock_entry.posting_date = self.service_date

		missing_warehouse_items = []

		for item in self.service_items:
			if not item.item_code:
				continue

			# ตรวจสอบว่า item เป็น stock item หรือไม่
			is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")
			
			# ข้าม item ที่ไม่ใช่ stock item (เช่น service)
			if not is_stock_item:
				continue

			# เลือกคลังจากรายการ ถ้าไม่มีให้ใช้ค่าจาก Settings
			s_warehouse = item.warehouse or settings.default_source_warehouse or settings.default_warehouse
			if not s_warehouse:
				missing_warehouse_items.append(item.item_code)
				continue

			stock_entry.append("items", {
				"item_code": item.item_code,
				"qty": item.qty,
				"s_warehouse": s_warehouse,
				"cost_center": item.cost_center or settings.default_cost_center,
				"expense_account": item.expense_account or settings.default_expense_account,
				"basic_rate": item.rate
			})

		if missing_warehouse_items:
			frappe.msgprint(
				"ไม่สามารถสร้าง Stock Entry สำหรับบางรายการ เนื่องจากไม่พบคลังสินค้า: "
				+ ", ".join(missing_warehouse_items),
				indicator="orange",
				title="ขาดข้อมูลคลังสินค้า"
			)

		if stock_entry.items:
			stock_entry.insert()
			stock_entry.submit()
			
			# เก็บ reference ของ Stock Entry
			self.db_set("stock_entry", stock_entry.name)
			
			frappe.msgprint(f"สร้าง Stock Entry: {stock_entry.name}")
	
	def update_vehicle_info(self):
		"""อัพเดทข้อมูลรถหลังการบริการ"""
		if self.vehicle and self.current_mileage:
			vehicle = frappe.get_doc("Vehicle", self.vehicle)
			vehicle.update_service_info(self)
			frappe.msgprint(f"อัพเดทข้อมูลรถ {self.vehicle} เรียบร้อยแล้ว")
	
	def create_sales_invoice(self):
		"""สร้างใบแจ้งหนี้"""
		if self.sales_invoice:
			frappe.throw("มีการสร้าง Sales Invoice ไปแล้ว")
		
		# ดึงการตั้งค่าจาก Settings
		settings = frappe.get_single("Truck Service Center Settings")
		
		# ดึง company
		company = settings.default_company or frappe.defaults.get_defaults().get("company") or frappe.db.get_single_value("Global Defaults", "default_company")
		
		sales_invoice = frappe.new_doc("Sales Invoice")
		sales_invoice.customer = self.customer
		sales_invoice.company = company
		sales_invoice.posting_date = self.service_date
		sales_invoice.set_posting_time = 1
		sales_invoice.due_date = self.service_date
		
		# ใช้ Payment Terms Template ถ้ามีการตั้งค่า
		if settings.payment_terms_template:
			sales_invoice.payment_terms_template = settings.payment_terms_template
		
		# เพิ่มรายการบริการและอะไหล่
		for item in self.service_items:
			if item.item_code:
				sales_invoice.append("items", {
					"item_code": item.item_code,
					"item_name": item.item_name or "",
					"description": item.description or "",
					"qty": flt(item.qty) or 1,
					"uom": item.uom,
					"rate": flt(item.rate) or 0,
					"warehouse": item.warehouse or settings.default_warehouse,
					"expense_account": item.expense_account or settings.default_expense_account,
					"cost_center": item.cost_center or settings.default_cost_center,
					"income_account": settings.default_income_account
				})
		
		# เพิ่มค่าแรง (ถ้ามี)
		if flt(self.labor_charges) > 0:
			# ตรวจสอบว่ามีการตั้งค่า Labor Item หรือไม่
			if not settings.labor_item:
				frappe.throw(
					"กรุณาตั้งค่า 'รายการสินค้าสำหรับค่าแรง' ใน Truck Service Center Settings ก่อนสร้าง Sales Invoice",
					title="ยังไม่ได้ตั้งค่า"
				)
			
			sales_invoice.append("items", {
				"item_code": settings.labor_item,
				"qty": 1,
				"rate": flt(self.labor_charges),
				"expense_account": settings.labor_expense_account,
				"cost_center": settings.labor_cost_center or settings.default_cost_center,
				"income_account": settings.default_income_account
			})
		
		# ตรวจสอบว่ามีรายการหรือไม่
		if not sales_invoice.items:
			frappe.throw("ไม่สามารถสร้าง Sales Invoice ได้เนื่องจากไม่มีรายการสินค้า")
		
		sales_invoice.insert()
		
		# Submit อัตโนมัติถ้ามีการตั้งค่า
		if settings.auto_submit_sales_invoice:
			sales_invoice.submit()
		
		# เก็บ reference
		self.db_set("sales_invoice", sales_invoice.name)
		
		frappe.msgprint(f"สร้าง Sales Invoice: {sales_invoice.name}")
		
		return sales_invoice.name


@frappe.whitelist()
def create_sales_invoice_from_service_order(service_order):
	"""สร้าง Sales Invoice จาก Service Order - สำหรับเรียกจาก client"""
	doc = frappe.get_doc("Service Order", service_order)
	return doc.create_sales_invoice()


@frappe.whitelist()
def get_item_rate(item_code, customer=None, price_list=None):
	"""ดึงราคาสินค้าจาก Item Price หรือ Standard Rate"""
	from frappe.utils import flt
	
	rate = 0
	
	# 1. พยายามดึงจาก Item Price ก่อน
	if not price_list:
		price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list") or "Standard Selling"
	
	item_price = frappe.db.get_value(
		"Item Price",
		{
			"item_code": item_code,
			"price_list": price_list,
			"selling": 1
		},
		"price_list_rate"
	)
	
	if item_price:
		rate = flt(item_price)
	else:
		# 2. ถ้าไม่มีใน Item Price ให้ดึงจาก Item
		item_data = frappe.db.get_value(
			"Item",
			item_code,
			["standard_rate", "item_name", "description", "stock_uom"],
			as_dict=1
		)
		
		if item_data:
			rate = flt(item_data.standard_rate)
			
			return {
				"rate": rate,
				"item_name": item_data.item_name,
				"description": item_data.description,
				"uom": item_data.stock_uom
			}
	
	# 3. ดึงข้อมูลเพิ่มเติมของ Item
	item_data = frappe.db.get_value(
		"Item",
		item_code,
		["item_name", "description", "stock_uom"],
		as_dict=1
	)
	
	return {
		"rate": rate,
		"item_name": item_data.item_name if item_data else "",
		"description": item_data.description if item_data else "",
		"uom": item_data.stock_uom if item_data else ""
	}

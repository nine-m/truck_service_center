# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class ServiceOrder(Document):
	def validate(self):
		self.calculate_totals()
		self.update_payment_status()
	
	def calculate_totals(self):
		"""คำนวณยอดรวมทั้งหมด"""
		# คำนวณยอดรวมอะไหล่
		self.total_parts_amount = 0
		for item in self.service_items:
			item.amount = flt(item.qty) * flt(item.rate)
			self.total_parts_amount += item.amount
		
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
		self.status = "Completed"
		self.save()
	
	def create_stock_entry(self):
		"""สร้าง Stock Entry เพื่อตัดสต็อกอะไหล่"""
		if not self.service_items:
			return
		
		# ตรวจสอบว่ามี items ที่ต้องตัดสต็อกหรือไม่
		has_stock_items = False
		for item in self.service_items:
			if item.warehouse:
				has_stock_items = True
				break
		
		if not has_stock_items:
			return
		
		stock_entry = frappe.new_doc("Stock Entry")
		stock_entry.stock_entry_type = "Material Issue"
		stock_entry.company = frappe.defaults.get_defaults().company
		stock_entry.set_posting_time = 1
		stock_entry.posting_date = self.service_date
		
		for item in self.service_items:
			if item.warehouse and item.item_code:
				stock_entry.append("items", {
					"item_code": item.item_code,
					"qty": item.qty,
					"s_warehouse": item.warehouse,
					"cost_center": item.cost_center,
					"expense_account": item.expense_account,
					"basic_rate": item.rate
				})
		
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
		
		sales_invoice = frappe.new_doc("Sales Invoice")
		sales_invoice.customer = self.customer
		sales_invoice.posting_date = self.service_date
		sales_invoice.due_date = self.service_date
		
		# เพิ่มรายการบริการและอะไหล่
		for item in self.service_items:
			sales_invoice.append("items", {
				"item_code": item.item_code,
				"item_name": item.item_name,
				"description": item.description,
				"qty": item.qty,
				"uom": item.uom,
				"rate": item.rate,
				"amount": item.amount,
				"warehouse": item.warehouse,
				"expense_account": item.expense_account,
				"cost_center": item.cost_center
			})
		
		# เพิ่มค่าแรง (ถ้ามี)
		if self.labor_charges:
			# ต้องมี Item สำหรับค่าแรงในระบบ
			labor_item = frappe.db.get_value("Item", {"item_name": "Labor Charge"}, "name")
			if labor_item:
				sales_invoice.append("items", {
					"item_code": labor_item,
					"qty": 1,
					"rate": self.labor_charges,
					"amount": self.labor_charges
				})
		
		sales_invoice.insert()
		
		# เก็บ reference
		self.db_set("sales_invoice", sales_invoice.name)
		
		frappe.msgprint(f"สร้าง Sales Invoice: {sales_invoice.name}")
		
		return sales_invoice.name

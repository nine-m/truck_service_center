# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class ServiceOrder(Document):
	def validate(self):
		self.check_material_issue_items()
		self.apply_service_package()
		self.calculate_totals()
		self.update_payment_status()
		self.update_material_issue_status()
	
	def check_material_issue_items(self):
		"""ตรวจสอบว่าไม่มีการลบแถวที่มี Material Issue ที่ submit ไปแล้ว"""
		if self.is_new():
			return
		
		# ดึงข้อมูลเดิมจาก database
		old_doc = self.get_doc_before_save()
		if not old_doc:
			return
		
		# สร้าง set ของ item names ที่มีอยู่ในเอกสารปัจจุบัน
		current_item_names = {item.name for item in self.service_items if item.name}
		
		# ตรวจสอบแต่ละ item ในเอกสารเดิม
		for old_item in old_doc.service_items:
			# ถ้า item ถูกลบออก (ไม่อยู่ใน current_item_names)
			if old_item.name and old_item.name not in current_item_names:
				# ตรวจสอบว่า item นี้มี Material Issue ที่ submit แล้วหรือไม่
				if old_item.material_issue:
					material_issue_status = frappe.db.get_value(
						"Stock Entry", 
						old_item.material_issue, 
						"docstatus"
					)
					
					if material_issue_status == 1:
						frappe.throw(
							f"ไม่สามารถลบรายการ '{old_item.item_name or old_item.item_code}' ได้ "
							f"เนื่องจากใบเบิกอะไหล่ {old_item.material_issue} ถูก submit ไปแล้ว<br>"
							f"กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบรายการ",
							title="ไม่สามารถลบรายการได้"
						)
	
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
	
	def update_material_issue_status(self):
		"""อัพเดทสถานะ Material Issue ในแต่ละ Item"""
		for item in self.service_items:
			if item.material_issue:
				# ดึงสถานะจาก Stock Entry
				status = frappe.db.get_value("Stock Entry", item.material_issue, "docstatus")
				if status == 0:
					item.material_issue_status = "Draft"
				elif status == 1:
					item.material_issue_status = "Submitted"
				elif status == 2:
					item.material_issue_status = "Cancelled"
			else:
				item.material_issue_status = None
	
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


@frappe.whitelist()
def create_material_issue(service_order, item_rows=None):
	"""สร้าง Material Issue สำหรับ items ที่ยังไม่มีใบเบิก
	
	Args:
		service_order: ชื่อของ Service Order
		item_rows: list ของ row indices ที่ต้องการสร้าง Material Issue (ถ้าไม่ระบุจะสร้างทั้งหมด)
	"""
	import json
	
	if isinstance(item_rows, str):
		item_rows = json.loads(item_rows)
	
	doc = frappe.get_doc("Service Order", service_order)
	
	# ดึง settings
	settings = frappe.get_single("Truck Service Center Settings")
	
	# สร้าง Stock Entry
	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.stock_entry_type = "Material Issue"
	stock_entry.company = settings.default_company or frappe.defaults.get_defaults().company
	stock_entry.set_posting_time = 1
	stock_entry.posting_date = doc.service_date
	stock_entry.custom_service_order = service_order  # Link กลับไป Service Order
	
	items_added = []
	
	for idx, item in enumerate(doc.service_items):
		# ถ้าระบุ item_rows ให้ตรวจสอบว่า item นี้อยู่ในรายการหรือไม่
		if item_rows and idx not in item_rows:
			continue
		
		# ข้าม item ที่มี Material Issue แล้ว
		if item.material_issue:
			continue
		
		# ตรวจสอบว่าเป็น stock item
		is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")
		if not is_stock_item:
			continue
		
		# เลือกคลัง
		s_warehouse = item.warehouse or settings.default_source_warehouse or settings.default_warehouse
		if not s_warehouse:
			frappe.msgprint(f"ไม่พบคลังสินค้าสำหรับ {item.item_code}", indicator="orange")
			continue
		
		stock_entry.append("items", {
			"item_code": item.item_code,
			"qty": item.qty,
			"s_warehouse": s_warehouse,
			"cost_center": item.cost_center or settings.default_cost_center,
			"expense_account": item.expense_account or settings.default_expense_account,
			"basic_rate": item.rate,
			"custom_service_order_item_idx": idx  # เก็บ index เพื่อ link กลับ
		})
		items_added.append(idx)
	
	if not stock_entry.items:
		frappe.throw("ไม่มีรายการที่สามารถสร้าง Material Issue ได้")
	
	stock_entry.insert()
	
	# อัพเดท Material Issue reference ใน Service Order Items
	for idx in items_added:
		doc.service_items[idx].material_issue = stock_entry.name
		doc.service_items[idx].material_issue_status = "Draft"
	
	doc.save()
	
	frappe.msgprint(f"สร้าง Material Issue: {stock_entry.name}")
	
	return stock_entry.name


@frappe.whitelist()
def sync_material_issue(service_order, material_issue):
	"""ซิงค์ข้อมูลจาก Material Issue กลับมายัง Service Order
	
	Args:
		service_order: ชื่อของ Service Order
		material_issue: ชื่อของ Stock Entry (Material Issue)
	"""
	doc = frappe.get_doc("Service Order", service_order)
	stock_entry = frappe.get_doc("Stock Entry", material_issue)
	
	# ตรวจสอบว่า Material Issue ยัง Draft อยู่หรือไม่
	if stock_entry.docstatus != 0:
		frappe.throw("สามารถ Sync ได้เฉพาะ Material Issue ที่อยู่ในสถานะ Draft เท่านั้น")
	
	# อัพเดทข้อมูลจาก Stock Entry กลับมายัง Service Order Items
	updated_items = []
	
	for stock_item in stock_entry.items:
		# หา item ใน Service Order ที่ตรงกัน
		idx = stock_item.get("custom_service_order_item_idx")
		
		if idx is not None and idx < len(doc.service_items):
			service_item = doc.service_items[idx]
			
			# อัพเดทข้อมูล
			service_item.qty = stock_item.qty
			service_item.rate = stock_item.basic_rate or stock_item.valuation_rate
			service_item.warehouse = stock_item.s_warehouse
			
			updated_items.append(service_item.item_code)
	
	doc.save()
	
	if updated_items:
		frappe.msgprint(f"Sync ข้อมูลจาก Material Issue เรียบร้อย: {', '.join(updated_items)}")
	else:
		frappe.msgprint("ไม่พบรายการที่ต้อง Sync", indicator="orange")
	
	return True


@frappe.whitelist()
def get_material_issue_summary(service_order):
	"""ดึงสรุปข้อมูล Material Issues ทั้งหมดของ Service Order
	
	Returns:
		dict: สถิติและรายการ Material Issues
	"""
	doc = frappe.get_doc("Service Order", service_order)
	
	# รวบรวม Material Issues ทั้งหมด
	material_issues = {}
	
	for item in doc.service_items:
		if item.material_issue:
			if item.material_issue not in material_issues:
				# ดึงข้อมูล Stock Entry
				stock_entry = frappe.db.get_value(
					"Stock Entry",
					item.material_issue,
					["name", "docstatus", "posting_date", "total_amount"],
					as_dict=1
				)
				
				if stock_entry:
					status_map = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
					material_issues[item.material_issue] = {
						"name": stock_entry.name,
						"status": status_map.get(stock_entry.docstatus, "Unknown"),
						"posting_date": stock_entry.posting_date,
						"total_amount": stock_entry.total_amount,
						"item_count": 0
					}
			
			# นับจำนวน items
			if item.material_issue in material_issues:
				material_issues[item.material_issue]["item_count"] += 1
	
	return {
		"total_count": len(material_issues),
		"material_issues": list(material_issues.values())
	}

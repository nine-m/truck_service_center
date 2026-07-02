# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.contacts.doctype.address.address import get_address_display
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class RepairQuotation(Document):
	def validate(self):
		self.set_tax_defaults()
		self.set_address_display()
		self.apply_service_packages()
		self.calculate_totals()
		self.validate_valid_until()
		self.update_status_on_save()

	def set_tax_defaults(self):
		"""ตั้งค่าภาษีเริ่มต้นจาก Settings"""
		settings = frappe.get_single("Truck Service Center Settings")
		if not self.tax_type:
			self.tax_type = settings.default_tax_type or "ราคาแยก VAT"
		if not self.vat_rate:
			self.vat_rate = flt(settings.vat_rate) or 7

	def set_address_display(self):
		"""ตั้งค่าการแสดงผลที่อยู่สำหรับ billing และ shipping address"""
		if self.customer_address:
			self.address_display = get_address_display(self.customer_address)
		else:
			self.address_display = ""

		if self.shipping_address_name:
			self.shipping_address = get_address_display(self.shipping_address_name)
		else:
			self.shipping_address = ""

	def apply_service_packages(self):
		"""นำรายการบริการและอะไหล่จากแพ็คเกจมาใส่อัตโนมัติ (รองรับหลาย package)"""
		if not self.service_packages:
			return

		# รวบรวม package names ที่ยังอยู่ในตาราง
		current_package_names = set()
		for pkg_row in self.service_packages:
			if pkg_row.service_package:
				current_package_names.add(pkg_row.service_package)

		# Cascade delete: ลบ service_types/service_items ที่ผูกกับ package ที่ถูกลบออก
		self.service_types = [
			st
			for st in self.service_types
			if not st.service_package or st.service_package in current_package_names
		]
		self.service_items = [
			si
			for si in self.service_items
			if not si.service_package or si.service_package in current_package_names
		]

		# สำหรับแต่ละ package ตรวจสอบว่าดึงข้อมูลแล้วหรือยัง
		for pkg_row in self.service_packages:
			if not pkg_row.service_package:
				continue

			pkg_name = pkg_row.service_package

			# ตรวจสอบว่ามี service_types ที่ผูกกับ package นี้อยู่แล้วหรือไม่
			has_service_types = any(st.service_package == pkg_name for st in self.service_types)

			if has_service_types:
				continue

			# ดึงข้อมูลจาก package
			package = frappe.get_doc("Service Package", pkg_name)

			if not package.is_active:
				frappe.throw(f"แพ็คเกจ {pkg_name} ถูกปิดการใช้งานแล้ว")

			discount_pct = flt(package.discount_percent)

			# เพิ่ม service types จาก package
			for st in package.package_service_types:
				self.append(
					"service_types",
					{
						"service_type": st.service_type,
						"service_type_group": st.service_type_group,
						"maintenance_type": st.maintenance_type,
						"estimated_time": st.estimated_time,
						"labor_charges": st.labor_rate,
						"discount_percentage": discount_pct,
						"service_package": pkg_name,
					},
				)

			# เพิ่ม parts จาก package
			for part in package.package_parts:
				self.append(
					"service_items",
					{
						"item_code": part.item_code,
						"item_name": part.item_name,
						"qty": part.qty,
						"uom": part.uom,
						"rate": part.rate,
						"discount_percentage": discount_pct,
						"service_package": pkg_name,
					},
				)

	def calculate_totals(self):
		"""คำนวณยอดรวมทั้งหมด (เหมือน Service Order)"""
		# คำนวณยอดรวมอะไหล่ (พร้อมส่วนลดระดับบรรทัด)
		self.total_parts_amount = 0
		for item in self.service_items:
			if not item.rate:
				rate = frappe.db.get_value("Item", item.item_code, "valuation_rate") or 0
				item.rate = rate
			self._calculate_line_discount(item)
			self.total_parts_amount += flt(item.amount)

		# คำนวณค่าแรงรวมและเวลารวม
		self.labor_charges = 0
		self.estimated_time = 0
		for service_type in self.service_types:
			self._calculate_service_type_discount(service_type)
			self.labor_charges += flt(service_type.amount)
			self.estimated_time += flt(service_type.estimated_time)

		# คำนวณยอดก่อนภาษี (subtotal หลังหักส่วนลดระดับเอกสาร)
		subtotal = flt(self.total_parts_amount) + flt(self.labor_charges) - flt(self.discount_amount)

		# คำนวณภาษีตามประเภท
		vat_rate = flt(self.vat_rate)

		if self.tax_type == "ราคารวม VAT" and vat_rate:
			self.tax_amount = flt(subtotal * vat_rate / (100 + vat_rate), 2)
			self.net_total = flt(subtotal - self.tax_amount, 2)
			self.total_amount = flt(subtotal, 2)
		elif self.tax_type == "ราคาแยก VAT" and vat_rate:
			self.net_total = flt(subtotal, 2)
			self.tax_amount = flt(subtotal * vat_rate / 100, 2)
			self.total_amount = flt(subtotal + self.tax_amount, 2)
		else:
			self.net_total = flt(subtotal, 2)
			self.tax_amount = 0
			self.total_amount = flt(subtotal, 2)

	def _calculate_line_discount(self, item):
		"""คำนวณส่วนลดระดับบรรทัดสำหรับ Repair Quotation Item"""
		rate = flt(item.rate)
		qty = flt(item.qty)

		if flt(item.discount_percentage) > 0:
			item.discount_amount = flt(rate * flt(item.discount_percentage) / 100, 2)

		if flt(item.discount_amount) > 0 and rate > 0 and not flt(item.discount_percentage):
			item.discount_percentage = flt(flt(item.discount_amount) / rate * 100, 2)

		discount_per_unit = flt(item.discount_amount)
		net_rate = flt(rate - discount_per_unit, 2)
		if net_rate < 0:
			net_rate = 0
		item.amount = flt(net_rate * qty, 2)

	def _calculate_service_type_discount(self, service_type):
		"""คำนวณส่วนลดระดับบรรทัดสำหรับ Repair Quotation Service Type"""
		labor = flt(service_type.labor_charges)

		if flt(service_type.discount_percentage) > 0:
			service_type.discount_amount = flt(labor * flt(service_type.discount_percentage) / 100, 2)

		if flt(service_type.discount_amount) > 0 and labor > 0 and not flt(service_type.discount_percentage):
			service_type.discount_percentage = flt(flt(service_type.discount_amount) / labor * 100, 2)

		discount = flt(service_type.discount_amount)
		net_labor = flt(labor - discount, 2)
		if net_labor < 0:
			net_labor = 0
		service_type.amount = flt(net_labor, 2)

	def validate_valid_until(self):
		"""ตรวจสอบวันหมดอายุ"""
		if self.valid_until and getdate(self.valid_until) < getdate(self.quotation_date):
			frappe.throw("วันที่ใช้ได้ถึงต้องมากกว่าหรือเท่ากับวันที่เสนอราคา")

	def update_status_on_save(self):
		"""อัพเดทสถานะอัตโนมัติ"""
		if self.status == "Draft":
			return

		# ตรวจสอบว่าหมดอายุหรือยัง
		if self.status == "Open" and self.valid_until and getdate(self.valid_until) < getdate(nowdate()):
			self.status = "Expired"


@frappe.whitelist()
def create_service_order_from_quotation(repair_quotation):
	"""สร้าง Service Order จากใบเสนอราคาซ่อม"""
	rq = frappe.get_doc("Repair Quotation", repair_quotation)
	rq.check_permission("write")

	if rq.service_order:
		frappe.throw(f"ใบเสนอราคานี้มี Service Order {rq.service_order} อยู่แล้ว")

	if rq.status not in ("Open", "Accepted"):
		frappe.throw("สามารถสร้าง Service Order ได้เฉพาะใบเสนอราคาที่มีสถานะ Open หรือ Accepted เท่านั้น")

	# สร้าง Service Order
	so = frappe.new_doc("Service Order")

	# ข้อมูลหลัก
	so.customer = rq.customer
	so.vehicle = rq.vehicle
	so.current_mileage = rq.current_mileage

	# ที่อยู่
	so.customer_address = rq.customer_address
	so.address_display = rq.address_display
	so.shipping_address_name = rq.shipping_address_name
	so.shipping_address = rq.shipping_address

	# ข้อมูลติดต่อ
	so.contact_person = rq.contact_person
	so.contact_number = rq.contact_number
	so.email = rq.email

	# แพ็คเกจบริการ (หลาย package)
	for pkg_row in rq.service_packages:
		so.append(
			"service_packages",
			{
				"service_package": pkg_row.service_package,
				"package_code": pkg_row.package_code,
				"package_name": pkg_row.package_name,
				"package_rate": pkg_row.package_rate,
				"discount_percent": pkg_row.discount_percent,
			},
		)

	# ประเภทบริการ
	for st in rq.service_types:
		so.append(
			"service_types",
			{
				"service_type_group": st.service_type_group,
				"service_type": st.service_type,
				"maintenance_type": st.maintenance_type,
				"estimated_time": st.estimated_time,
				"labor_charges": st.labor_charges,
				"discount_percentage": st.discount_percentage,
				"discount_amount": st.discount_amount,
				"amount": st.amount,
				"repair_position": st.repair_position,
				"repair_cause": st.repair_cause,
				"remark": st.remark,
				"service_package": st.service_package,
			},
		)

	# รายการอะไหล่
	default_warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
	for item in rq.service_items:
		so.append(
			"service_items",
			{
				"item_code": item.item_code,
				"item_name": item.item_name,
				"description": item.description,
				"qty": item.qty,
				"uom": item.uom,
				"rate": item.rate,
				"discount_percentage": item.discount_percentage,
				"discount_amount": item.discount_amount,
				"amount": item.amount,
				"warehouse": default_warehouse,
				"service_package": item.service_package,
			},
		)

	# ราคา
	so.tax_type = rq.tax_type
	so.vat_rate = rq.vat_rate
	so.discount_amount = rq.discount_amount

	# หมายเหตุ
	so.customer_complaints = rq.customer_complaints
	so.recommendations = rq.recommendations

	so.insert()

	# อัพเดท repair quotation
	rq.db_set("service_order", so.name)
	rq.db_set("status", "Accepted")

	frappe.msgprint(f"สร้าง Service Order {so.name} เรียบร้อยแล้ว", alert=True, indicator="green")

	return so.name


@frappe.whitelist()
def get_item_rate(item_code, customer=None):
	"""ดึงราคาสินค้าจาก Item Price หรือ standard_rate"""
	item = frappe.get_doc("Item", item_code)
	rate = 0

	# ลองดึงจาก Item Price (Selling)
	if customer:
		item_price = frappe.db.get_value(
			"Item Price", {"item_code": item_code, "selling": 1, "customer": customer}, "price_list_rate"
		)
		if item_price:
			rate = item_price

	if not rate:
		# ดึงจาก Item Price (Selling) ทั่วไป
		item_price = frappe.db.get_value(
			"Item Price",
			{"item_code": item_code, "selling": 1, "customer": ["is", "not set"]},
			"price_list_rate",
		)
		if item_price:
			rate = item_price

	if not rate:
		rate = item.standard_rate or item.valuation_rate or 0

	return {
		"item_code": item.name,
		"item_name": item.item_name,
		"description": item.description,
		"uom": item.stock_uom,
		"rate": rate,
	}


@frappe.whitelist()
def get_item_by_barcode(barcode, customer=None):
	"""ค้นหาสินค้าจากบาร์โค้ด"""
	# ค้นหาจาก Item Barcode
	item_code = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")

	if not item_code:
		# ค้นหาจาก Item.name ตรงๆ
		if frappe.db.exists("Item", barcode):
			item_code = barcode

	if not item_code:
		return None

	return get_item_rate(item_code, customer)

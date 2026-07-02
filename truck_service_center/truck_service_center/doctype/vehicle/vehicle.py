# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import add_months, getdate


class Vehicle(Document):
	def validate(self):
		self.validate_mileage()
		self.calculate_next_service()

	def validate_mileage(self):
		"""ตรวจสอบว่าเลขไมล์ไม่ย้อนหลัง"""
		if self.current_mileage and self.last_service_mileage:
			if self.current_mileage < self.last_service_mileage:
				frappe.throw("เลขไมล์ปัจจุบันต้องมากกว่าหรือเท่ากับเลขไมล์บริการล่าสุด")

	def calculate_next_service(self):
		"""คำนวณกำหนดการบริการครั้งถัดไป"""
		if self.last_service_date and self.service_interval_months:
			self.next_service_due = add_months(getdate(self.last_service_date), self.service_interval_months)

		if self.last_service_mileage and self.service_interval_km:
			self.next_service_mileage = self.last_service_mileage + self.service_interval_km

	def update_service_info(self, service_order):
		"""อัพเดทข้อมูลหลังการบริการ"""
		self.last_service_date = service_order.service_date
		self.last_service_mileage = service_order.current_mileage
		self.current_mileage = service_order.current_mileage
		self.calculate_next_service()
		self.save()

	def get_service_history(self):
		"""ดึงประวัติการบริการ"""
		return frappe.get_all(
			"Service Order",
			filters={"vehicle": self.name},
			fields=["name", "service_date", "service_type", "total_amount", "status"],
			order_by="service_date desc",
		)

	def is_service_due(self):
		"""ตรวจสอบว่าถึงกำหนดบริการหรือไม่"""
		today = getdate()
		due_by_date = False
		due_by_mileage = False

		if self.next_service_due and today >= getdate(self.next_service_due):
			due_by_date = True

		if self.next_service_mileage and self.current_mileage >= self.next_service_mileage:
			due_by_mileage = True

		return due_by_date or due_by_mileage

	def get_upcoming_expirations(self):
		"""แจ้งเตือนเอกสารใกล้หมดอายุ"""
		today = getdate()
		warnings = []

		expirations = {
			"insurance_expiry": "ประกันภัย",
			"registration_expiry": "ทะเบียนรถ",
			"road_tax_expiry": "ภาษีรถ",
			"inspection_expiry": "ตรวจสภาพรถ",
		}

		for field, label in expirations.items():
			expiry_date = self.get(field)
			if expiry_date:
				days_left = (getdate(expiry_date) - today).days
				if days_left <= 30:
					warnings.append({"type": label, "expiry_date": expiry_date, "days_left": days_left})

		return warnings


@frappe.whitelist()
def check_service_due(vehicle):
	"""ตรวจสอบว่ารถถึงกำหนดบริการหรือไม่ - สำหรับเรียกจาก client"""
	doc = frappe.get_doc("Vehicle", vehicle)
	doc.check_permission("read")
	return doc.is_service_due()


@frappe.whitelist()
def get_vehicle_service_history(vehicle):
	"""ดึงประวัติการบริการของรถ - สำหรับเรียกจาก client"""
	doc = frappe.get_doc("Vehicle", vehicle)
	doc.check_permission("read")
	return doc.get_service_history()


@frappe.whitelist()
def get_customer_contact_info(customer):
	"""ดึงข้อมูลติดต่อจาก Customer - สำหรับเรียกจาก client"""
	frappe.has_permission("Customer", doc=customer, throw=True)
	result = {}

	customer_doc = frappe.get_doc("Customer", customer)

	# ดึงจาก primary contact ของ Customer
	if customer_doc.customer_primary_contact:
		contact = frappe.get_doc("Contact", customer_doc.customer_primary_contact)
		result["contact_person"] = contact.full_name or ""
		result["contact_number"] = contact.mobile_no or contact.phone or ""
		result["email"] = contact.email_id or ""
	else:
		# ถ้าไม่มี primary contact ให้ลองหา Contact ที่ผูกกับ Customer ผ่าน Dynamic Link
		contacts = frappe.get_all(
			"Contact",
			filters=[
				["Dynamic Link", "link_doctype", "=", "Customer"],
				["Dynamic Link", "link_name", "=", customer],
			],
			fields=["name", "full_name", "email_id", "mobile_no", "phone"],
			order_by="is_primary_contact DESC",
			limit=1,
		)
		if contacts:
			c = contacts[0]
			result["contact_person"] = c.full_name or ""
			result["contact_number"] = c.mobile_no or c.phone or ""
			result["email"] = c.email_id or ""

	return result


@frappe.whitelist()
def get_vehicle_expirations(vehicle):
	"""ดึงรายการเอกสารที่ใกล้หมดอายุ - สำหรับเรียกจาก client"""
	doc = frappe.get_doc("Vehicle", vehicle)
	doc.check_permission("read")
	return doc.get_upcoming_expirations()

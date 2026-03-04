# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, add_to_date, now_datetime, format_datetime, flt
from frappe.contacts.doctype.address.address import get_address_display


class ServiceAppointment(Document):
	def validate(self):
		self.set_address_display()
		self.validate_appointment_datetime()
		self.check_slot_availability()
		self.sync_vehicle_info()
		self.set_slot_datetimes()
		self.calculate_estimated_duration()
		self.calculate_totals()

	def calculate_estimated_duration(self):
		"""คำนวณระยะเวลาโดยประมาณจาก service_types child table"""
		total = sum(flt(row.estimated_time) for row in (self.service_types or []))
		self.estimated_duration = total

	def calculate_totals(self):
		"""คำนวณยอดรวมราคาจาก service_types และ service_items"""
		# รวมค่าแรง
		self.total_labor_charges = sum(flt(row.labor_charges) for row in (self.service_types or []))

		# รวมค่าอะไหล่ (คำนวณ amount ของแต่ละรายการด้วย)
		for item in (self.service_items or []):
			item.amount = flt(item.qty) * flt(item.rate)
		self.total_parts_amount = sum(flt(row.amount) for row in (self.service_items or []))

		# ยอดรวมทั้งหมด
		self.total_amount = flt(self.total_labor_charges) + flt(self.total_parts_amount)

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
	
	def validate_appointment_datetime(self):
		"""ตรวจสอบวันเวลานัดหมายต้องไม่อยู่ในอดีต"""
		if self.appointment_date:
			from frappe.utils import getdate, today
			if getdate(self.appointment_date) < getdate(today()):
				frappe.throw("ไม่สามารถนัดหมายย้อนหลังได้")
	
	def check_slot_availability(self):
		"""ตรวจสอบว่า slot ยังมีที่ว่างหรือไม่"""
		if not self.appointment_slot or not self.appointment_date:
			return
		
		# ดึงข้อมูล capacity ของ slot
		slot = frappe.get_doc("Service Appointment Slot", self.appointment_slot)
		
		if not slot.is_active:
			frappe.throw(f"Slot {slot.slot_name} ปิดใช้งานแล้ว")
		
		# นับจำนวนนัดหมายที่จองแล้วใน slot นี้ (ไม่รวมตัวเอง)
		booked_count = frappe.db.count(
			"Service Appointment",
			filters={
				"appointment_date": self.appointment_date,
				"appointment_slot": self.appointment_slot,
				"status": ["not in", ["Cancelled", "No Show"]],
				"name": ["!=", self.name or ""],
				"docstatus": ["!=", 2]
			}
		)
		
		if booked_count >= slot.capacity:
			frappe.throw(
				f"Slot {slot.slot_name} เต็มแล้ว (ความจุ: {slot.capacity} คัน)",
				title="ไม่สามารถจองได้"
			)

	def sync_vehicle_info(self):
		"""ซิงค์ข้อมูลจาก Vehicle: license_plate และ customer"""
		if not self.vehicle:
			return
		
		plate = frappe.db.get_value("Vehicle", self.vehicle, "license_plate")
		if plate and self.license_plate != plate:
			self.license_plate = plate
		
		if not self.customer:
			cust = frappe.db.get_value("Vehicle", self.vehicle, "customer")
			if cust:
				self.customer = cust

	def set_slot_datetimes(self):
		"""คำนวณ start/end datetime จาก slot เวลาและวันที่นัดหมาย"""
		if not (self.appointment_date and self.appointment_slot):
			self.appointment_start = self.appointment_date
			self.appointment_end = self.appointment_date
			self.all_day = 1
			self.display_start_time = format_datetime(self.appointment_start) if self.appointment_start else ""
			self.display_end_time = format_datetime(self.appointment_end) if self.appointment_end else ""
			return

		slot = frappe.db.get_value(
			"Service Appointment Slot",
			self.appointment_slot,
			["start_time", "end_time"],
			as_dict=1,
		)

		if not slot or not slot.start_time or not slot.end_time:
			self.appointment_start = self.appointment_date
			self.appointment_end = self.appointment_date
			self.all_day = 1
			self.display_start_time = format_datetime(self.appointment_start) if self.appointment_start else ""
			self.display_end_time = format_datetime(self.appointment_end) if self.appointment_end else ""
			return

		self.appointment_start = get_datetime(f"{self.appointment_date} {slot.start_time}")
		self.appointment_end = get_datetime(f"{self.appointment_date} {slot.end_time}")
		self.all_day = 0
		self.display_start_time = format_datetime(self.appointment_start)
		self.display_end_time = format_datetime(self.appointment_end)
	
	def on_submit(self):
		"""เมื่อยืนยันนัดหมาย"""
		self.status = "Confirmed"
		self.save()
	
	def on_cancel(self):
		"""เมื่อยกเลิกนัดหมาย"""
		self.status = "Cancelled"
		self.save()
	
	def create_service_order(self):
		"""สร้าง Service Order จากนัดหมาย"""
		if self.service_order:
			frappe.throw("มีการสร้าง Service Order ไปแล้ว")
		
		service_order = frappe.new_doc("Service Order")
		service_order.customer = self.customer
		service_order.vehicle = self.vehicle
		service_order.service_date = self.appointment_date
		service_order.technician = self.assigned_technician
		
		# ส่งที่อยู่ไปยัง Service Order
		if self.customer_address:
			service_order.customer_address = self.customer_address
			service_order.address_display = self.address_display
		if self.shipping_address_name:
			service_order.shipping_address_name = self.shipping_address_name
			service_order.shipping_address = self.shipping_address
		
		# รวม customer_complaints จาก repair_cause และ service_remark
		complaints = []
		if self.repair_cause:
			complaints.append(f"สาเหตุที่ซ่อม: {self.repair_cause}")
		if self.service_remark:
			complaints.append(f"หมายเหตุ: {self.service_remark}")
		if complaints:
			service_order.customer_complaints = "\n".join(complaints)

		# ดึงข้อมูลไมล์จากรถปัจจุบัน
		if self.vehicle:
			vehicle_data = frappe.db.get_value(
				"Vehicle", self.vehicle, ["current_mileage"], as_dict=1
			) or {}
			if vehicle_data.get("current_mileage"):
				service_order.current_mileage = vehicle_data.get("current_mileage")

		# คัดลอกแพ็คเกจบริการ (หลาย package)
		for pkg_row in (self.service_packages or []):
			service_order.append("service_packages", {
				"service_package": pkg_row.service_package,
				"package_code": pkg_row.package_code,
				"package_name": pkg_row.package_name,
				"package_rate": pkg_row.package_rate,
				"discount_percent": pkg_row.discount_percent,
			})
		
		# คัดลอก service types จากตาราง (ถ้ามี)
		if self.service_types:
			for st_row in self.service_types:
				service_order.append("service_types", {
					"service_type": st_row.service_type,
					"service_type_group": st_row.service_type_group,
					"maintenance_type": st_row.maintenance_type,
					"estimated_time": st_row.estimated_time,
					"labor_charges": st_row.labor_charges,
					"service_package": st_row.service_package,
					"remark": st_row.remark,
				})
		# คัดลอก service items (อะไหล่)
		for item_row in (self.service_items or []):
			service_order.append("service_items", {
				"item_code": item_row.item_code,
				"item_name": item_row.item_name,
				"qty": item_row.qty,
				"uom": item_row.uom,
				"rate": item_row.rate,
				"service_package": item_row.service_package,
			})
		
		service_order.insert()
		
		# เก็บ reference
		self.db_set("service_order", service_order.name)
		self.db_set("status", "In Progress")
		
		frappe.msgprint(f"สร้าง Service Order: {service_order.name}")
		
		return service_order.name


@frappe.whitelist()
def create_service_order_from_appointment(appointment):
	"""สร้าง Service Order จากนัดหมาย - สำหรับเรียกจาก client"""
	doc = frappe.get_doc("Service Appointment", appointment)
	return doc.create_service_order()


@frappe.whitelist()
def get_available_slots(date):
	"""ดึงช่วงเวลาว่างในวันที่กำหนด พร้อม capacity"""
	from truck_service_center.truck_service_center.doctype.service_appointment_slot.service_appointment_slot import get_slot_availability
	
	slots = get_slot_availability(date)
	
	# กรองเฉพาะ slot ที่ยังมีที่ว่าง
	available = [s for s in slots if not s['is_full']]
	
	return available


@frappe.whitelist()
def backfill_license_plate():
	"""เติมค่าทะเบียนรถใน Service Appointment ที่ยังว่างอยู่"""
	docs = frappe.get_all(
		"Service Appointment",
		filters={
			"vehicle": ["!=", None],
			"license_plate": ["in", [None, ""]]
		},
		fields=["name", "vehicle"]
	)
	updated = 0
	for d in docs:
		plate = frappe.db.get_value("Vehicle", d["vehicle"], "license_plate")
		if plate:
			frappe.db.set_value("Service Appointment", d["name"], "license_plate", plate)
			updated += 1
	return {"updated": updated}


@frappe.whitelist()
def get_party_shipping_address(doctype, name):
	"""Wrapper for erpnext get_party_shipping_address"""
	from erpnext.accounts.party import get_party_shipping_address as _get_party_shipping_address
	return _get_party_shipping_address(doctype, name)

# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_time


class ServiceAppointmentSlot(Document):
	def validate(self):
		self.validate_time_range()
	
	def validate_time_range(self):
		"""ตรวจสอบว่าเวลาสิ้นสุดมากกว่าเวลาเริ่ม"""
		if self.start_time and self.end_time:
			start = get_time(self.start_time)
			end = get_time(self.end_time)
			if end <= start:
				frappe.throw("เวลาสิ้นสุดต้องมากกว่าเวลาเริ่ม")


@frappe.whitelist()
def get_slot_availability(date, slot=None):
	"""ดึงข้อมูล availability ของ slots ในวันที่กำหนด"""
	from frappe.utils import getdate
	
	# ดึงข้อมูล slots ที่เปิดใช้งาน
	slots = frappe.get_all(
		"Service Appointment Slot",
		filters={"is_active": 1},
		fields=["name", "slot_name", "start_time", "end_time", "capacity"],
		order_by="start_time asc"
	)
	
	if not slots:
		return []
	
	# กรองเฉพาะ slot ที่ระบุ (ถ้ามี)
	if slot:
		slots = [s for s in slots if s.name == slot]
	
	# นับจำนวนนัดหมายที่จองแล้วในแต่ละ slot
	date = getdate(date)
	result = []
	
	for slot_doc in slots:
		booked_count = frappe.db.count(
			"Service Appointment",
			filters={
				"appointment_date": date,
				"appointment_slot": slot_doc.name,
				"status": ["not in", ["Cancelled", "No Show"]],
				"docstatus": ["!=", 2]
			}
		)
		
		available = slot_doc.capacity - booked_count
		result.append({
			"slot": slot_doc.name,
			"slot_name": slot_doc.slot_name,
			"start_time": str(slot_doc.start_time),
			"end_time": str(slot_doc.end_time),
			"capacity": slot_doc.capacity,
			"booked": booked_count,
			"available": available,
			"is_full": available <= 0
		})
	
	return result

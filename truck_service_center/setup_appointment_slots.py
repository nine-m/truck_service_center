"""
สคริปต์สร้าง default time slots สำหรับระบบนัดหมาย
รันคำสั่ง: bench --site development.localhost execute truck_service_center.setup_appointment_slots
"""

import frappe

def execute():
	"""สร้าง default appointment slots"""
	
	# กำหนด slots เริ่มต้น (8:00-17:00, แบ่งเป็นช่วงละ 2 ชั่วโมง)
	default_slots = [
		{
			"slot_name": "เช้า 08:00-10:00",
			"start_time": "08:00:00",
			"end_time": "10:00:00",
			"capacity": 3,  # รับได้ 3 คันต่อช่วง
			"is_active": 1
		},
		{
			"slot_name": "เช้า 10:00-12:00",
			"start_time": "10:00:00",
			"end_time": "12:00:00",
			"capacity": 3,
			"is_active": 1
		},
		{
			"slot_name": "บ่าย 13:00-15:00",
			"start_time": "13:00:00",
			"end_time": "15:00:00",
			"capacity": 3,
			"is_active": 1
		},
		{
			"slot_name": "บ่าย 15:00-17:00",
			"start_time": "15:00:00",
			"end_time": "17:00:00",
			"capacity": 2,  # ช่วงท้ายรับน้อยกว่า
			"is_active": 1
		}
	]
	
	created = 0
	for slot_data in default_slots:
		# ตรวจสอบว่ามี slot นี้แล้วหรือไม่
		if not frappe.db.exists("Service Appointment Slot", slot_data["slot_name"]):
			slot = frappe.new_doc("Service Appointment Slot")
			slot.update(slot_data)
			slot.insert()
			created += 1
			print(f"Created: {slot_data['slot_name']}")
		else:
			print(f"Already exists: {slot_data['slot_name']}")
	
	frappe.db.commit()
	print(f"\nTotal created: {created} slots")
	print("Done!")

if __name__ == "__main__":
	execute()

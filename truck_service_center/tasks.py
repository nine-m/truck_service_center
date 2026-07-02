# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""Scheduled tasks (ดู scheduler_events ใน hooks.py — รันวันละครั้ง)

การแจ้งเตือนส่งเป็น Notification Log (กระดิ่งใน Desk) ถึงผู้ใช้ที่มี role
Service Manager / Service User โดย subject ถูกออกแบบให้คงที่ต่อเหตุการณ์
(รถ + ประเภท + วันครบกำหนด) เพื่อใช้กันการแจ้งซ้ำ — เหตุการณ์เดียวกัน
แจ้งผู้ใช้แต่ละคนครั้งเดียว จนกว่าวันครบกำหนดจะเปลี่ยน (เช่น ต่อประกันแล้ว)
"""

import frappe
from frappe.utils import add_days, cint, formatdate, getdate, nowdate
from frappe.utils.user import get_users_with_role

NOTIFY_ROLES = ("Service Manager", "Service User")

# ฟิลด์วันหมดอายุบน Vehicle → ป้ายชื่อภาษาไทย
EXPIRY_FIELDS = {
	"insurance_expiry": "ประกันภัย",
	"registration_expiry": "ทะเบียนรถ",
	"road_tax_expiry": "ภาษีรถ",
	"inspection_expiry": "ตรวจสภาพรถ",
}


def _setting_enabled(fieldname):
	"""อ่าน toggle จากค่าดิบในตาราง Singles — ฟิลด์ Check ที่ยังไม่เคยบันทึกจะเป็น NULL
	(ทั้ง frappe.get_single และ get_single_value cast เป็น 0 แยกไม่ออกจากตั้งใจปิด)
	NULL ถือว่าเปิดใช้งาน — ปกติ patch set_notification_defaults เติมค่าให้แล้ว นี่คือกันเหนียว"""
	value = frappe.db.get_value(
		"Singles",
		{"doctype": "Truck Service Center Settings", "field": fieldname},
		"value",
		order_by=None,
	)
	return True if value is None else bool(cint(value))


def _get_recipients():
	users = set()
	for role in NOTIFY_ROLES:
		users.update(get_users_with_role(role))
	return sorted(users)


def _notify(users, subject, content, document_type, document_name):
	"""สร้าง Notification Log ให้ผู้ใช้แต่ละคน (ข้ามถ้าเคยแจ้ง subject เดียวกันแล้ว)"""
	for user in users:
		if frappe.db.exists("Notification Log", {"subject": subject, "for_user": user}):
			continue

		notification = frappe.new_doc("Notification Log")
		notification.for_user = user
		notification.type = "Alert"
		notification.document_type = document_type
		notification.document_name = document_name
		notification.subject = subject
		notification.email_content = content
		notification.insert(ignore_permissions=True)


def notify_vehicle_expirations():
	"""แจ้งเตือนเอกสารรถใกล้หมดอายุ/หมดอายุแล้ว (ประกัน ทะเบียน ภาษี ตรวจสภาพ)"""
	if not _setting_enabled("enable_expiry_notifications"):
		return

	notice_days = (
		cint(frappe.db.get_single_value("Truck Service Center Settings", "expiry_notice_days")) or 30
	)
	cutoff = add_days(nowdate(), notice_days)

	users = _get_recipients()
	if not users:
		return

	for field, label in EXPIRY_FIELDS.items():
		# ต้องใส่ ["is", "set"] คู่กับการเทียบวัน — frappe แปลงเงื่อนไขเป็น ifnull(field, '')
		# ทำให้ค่า NULL กลายเป็น '' ซึ่งน้อยกว่าทุกวันที่ แล้วรถที่ไม่ได้กรอกจะหลุดเข้ามา
		vehicles = frappe.get_all(
			"Vehicle",
			filters=[
				["Vehicle", "status", "=", "Active"],
				["Vehicle", field, "is", "set"],
				["Vehicle", field, "<=", cutoff],
			],
			fields=["name", "customer", field],
		)

		for vehicle in vehicles:
			if not vehicle.get(field):
				continue
			expiry = getdate(vehicle.get(field))
			days_left = (expiry - getdate(nowdate())).days

			if days_left < 0:
				subject = f"{label}ของรถ {vehicle.name} หมดอายุแล้ว (ตั้งแต่ {formatdate(expiry)})"
			else:
				subject = f"{label}ของรถ {vehicle.name} จะหมดอายุวันที่ {formatdate(expiry)}"

			content = (
				f"รถ: {vehicle.name}<br>"
				f"ลูกค้า: {vehicle.customer or '-'}<br>"
				f"{label} ครบกำหนด: {formatdate(expiry)}"
				+ (f" (อีก {days_left} วัน)" if days_left >= 0 else f" (เกินมา {-days_left} วัน)")
			)

			_notify(users, subject, content, "Vehicle", vehicle.name)


def notify_service_due():
	"""แจ้งเตือนรถถึง/ใกล้ถึงกำหนดบริการ ตามวันที่หรือเลขไมล์"""
	if not _setting_enabled("enable_service_due_notifications"):
		return

	notice_days = (
		cint(frappe.db.get_single_value("Truck Service Center Settings", "service_due_notice_days")) or 7
	)
	cutoff = add_days(nowdate(), notice_days)

	users = _get_recipients()
	if not users:
		return

	# เทียบเลขไมล์ข้ามคอลัมน์ใน filter ตรง ๆ ไม่ได้ — คัดหยาบด้วย or_filters แล้วกรองจริงด้านล่าง
	vehicles = frappe.get_all(
		"Vehicle",
		filters={"status": "Active"},
		or_filters=[
			["next_service_due", "<=", cutoff],
			["next_service_mileage", ">", 0],
		],
		fields=["name", "customer", "next_service_due", "next_service_mileage", "current_mileage"],
	)

	for vehicle in vehicles:
		due_parts = []

		if vehicle.next_service_due and getdate(vehicle.next_service_due) <= getdate(cutoff):
			due_parts.append(f"ครบกำหนดวันที่ {formatdate(vehicle.next_service_due)}")

		if (
			vehicle.next_service_mileage
			and vehicle.current_mileage
			and cint(vehicle.current_mileage) >= cint(vehicle.next_service_mileage)
		):
			due_parts.append(
				f"เลขไมล์ถึงกำหนด ({cint(vehicle.current_mileage):,} ≥ {cint(vehicle.next_service_mileage):,} กม.)"
			)

		if not due_parts:
			continue

		subject = f"รถ {vehicle.name} ถึงกำหนดบริการ — {', '.join(due_parts)}"
		content = (
			f"รถ: {vehicle.name}<br>"
			f"ลูกค้า: {vehicle.customer or '-'}<br>"
			f"{'<br>'.join(due_parts)}<br><br>"
			"แนะนำให้ติดต่อลูกค้าเพื่อนัดหมายเข้ารับบริการ"
		)

		_notify(users, subject, content, "Vehicle", vehicle.name)


def mark_expired_quotations():
	"""เปลี่ยนสถานะใบเสนอราคาที่เลยวันที่ใช้ได้ (valid_until) จาก Open เป็น Expired"""
	expired = frappe.get_all(
		"Repair Quotation",
		filters={"status": "Open", "valid_until": ["<", nowdate()]},
		pluck="name",
	)

	for name in expired:
		frappe.db.set_value("Repair Quotation", name, "status", "Expired")

	if expired:
		frappe.logger().info(f"truck_service_center: marked {len(expired)} repair quotation(s) as Expired")

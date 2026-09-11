# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe

from truck_service_center.truck_service_center.doctype.bay_type.bay_type import get_default_bay_type

PIT = "PIT"
GENERAL = "GENERAL"

# ค่าเดิมของ Service Appointment Bay.work_type (Select) ก่อนเปลี่ยนเป็น Link → Bay Type
LEGACY_PIT_WORK_TYPE = "งานใต้ท้อง (ใช้หลุม)"


def execute():
	"""ย้ายข้อมูลจากธง has_pit / requires_pit / work_type มาเป็น Bay Type

	patch อยู่ใน [post_model_sync] คอลัมน์ใหม่จึงถูกสร้างแล้ว ส่วนคอลัมน์เก่ายังอยู่
	(Frappe ไม่ drop column เมื่อฟิลด์หายจาก JSON — หายจริงเมื่อรัน bench trim-tables)
	แต่ก็ยังต้องเช็ค has_column ทุกจุด เผื่อ site ที่ trim ไปแล้ว

	เติมเฉพาะแถวที่ยังว่าง จึงรันซ้ำได้ไม่ทับค่าที่ผู้ใช้แก้เอง และ update_modified=False
	เพื่อไม่ให้ timestamp ของ master ทั้งตารางขยับจากการ migrate
	"""
	default_bay_type = get_default_bay_type()

	bays = _migrate_service_bays(default_bay_type)
	service_types = _migrate_service_types()
	appointment_bays = _migrate_appointment_bays(default_bay_type)

	print(
		f"✓ ย้ายข้อมูลประเภทช่องจอด: ช่องจอด {bays} รายการ, "
		f"ประเภทบริการ {service_types} รายการ, แถวช่องจอดในนัดหมาย {appointment_bays} รายการ"
	)


def _resolve(code, default_bay_type):
	"""รหัสที่ seed ไว้ ถ้าไม่มี (ผู้ใช้ลบ/เปลี่ยนรหัสเอง) ถอยไปใช้ประเภทเริ่มต้นแทน
	ดีกว่าเขียน link ที่ชี้ไปหาเอกสารที่ไม่มีอยู่จริง
	"""
	if frappe.db.exists("Bay Type", code):
		return code
	return default_bay_type


def _migrate_service_bays(default_bay_type):
	"""ช่องจอด: has_pit → PIT ไม่งั้น GENERAL, ที่เหลือ (ช่องที่สร้างหลังฟิลด์หาย) → ประเภทเริ่มต้น"""
	pit = _resolve(PIT, default_bay_type)
	general = _resolve(GENERAL, default_bay_type)

	column = "has_pit" if frappe.db.has_column("Service Bay", "has_pit") else "0"
	rows = frappe.db.sql(
		f"select name, {column} as has_pit from `tabService Bay` where ifnull(bay_type, '') = ''",
		as_dict=True,
	)

	updated = 0
	for row in rows:
		bay_type = pit if row.has_pit else general
		if not bay_type:
			continue
		frappe.db.set_value("Service Bay", row.name, "bay_type", bay_type, update_modified=False)
		updated += 1

	return updated


def _migrate_service_types():
	"""ประเภทบริการ: requires_pit → PIT ส่วนที่เหลือ **ปล่อยว่าง** = ตามประเภทเริ่มต้นของระบบ

	ปล่อยว่างไว้ดีกว่าเขียน GENERAL ลงไปทุกแถว เพราะศูนย์ที่เปลี่ยนประเภทเริ่มต้นทีหลัง
	จะได้ไม่ต้องไล่แก้ทีละรายการ
	"""
	if not frappe.db.has_column("Service Type", "requires_pit"):
		return 0

	pit = _resolve(PIT, None)
	if not pit:
		return 0

	rows = frappe.db.sql_list(
		"select name from `tabService Type` where ifnull(bay_type, '') = '' and ifnull(requires_pit, 0) = 1"
	)
	for name in rows:
		frappe.db.set_value("Service Type", name, "bay_type", pit, update_modified=False)

	return len(rows)


def _migrate_appointment_bays(default_bay_type):
	"""แถวช่องจอดในนัดหมาย: work_type เดิมเป็นงานใต้ท้อง → PIT ไม่งั้น GENERAL"""
	pit = _resolve(PIT, default_bay_type)
	general = _resolve(GENERAL, default_bay_type)

	has_legacy = frappe.db.has_column("Service Appointment Bay", "work_type")
	column = "work_type" if has_legacy else "''"
	rows = frappe.db.sql(
		f"select name, {column} as work_type from `tabService Appointment Bay` "
		"where ifnull(bay_type, '') = ''",
		as_dict=True,
	)

	updated = 0
	for row in rows:
		bay_type = pit if row.work_type == LEGACY_PIT_WORK_TYPE else general
		if not bay_type:
			continue
		frappe.db.set_value("Service Appointment Bay", row.name, "bay_type", bay_type, update_modified=False)
		updated += 1

	return updated

# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""API สำหรับพอร์ทัลช่าง (/service-order-portal)

เปิดเฉพาะสิ่งที่ช่างต้องแก้หน้างานจริง ไม่ได้เปิด doctype ทั้งใบ
ทุก endpoint ตรวจ 3 ชั้น: สิทธิ์ write ของ doctype → ต้องเป็นช่างในใบนั้น → เอกสารต้องยังเป็น draft
"""

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt

from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	receive_vehicle,
)

# ช่องช่างผู้รับผิดชอบทั้ง 4 ช่องของ Service Order
TECHNICIAN_FIELDS = ("technician", "technician_2", "technician_3", "technician_4")

# role ที่ดูแลงานช่างได้ทุกใบ ไม่ต้องถูกระบุชื่อในใบงาน
MANAGER_ROLES = {"Technician Manager", "Service Manager", "System Manager"}

# สถานะที่ยังให้แก้ข้อมูลจากพอร์ทัลได้ (ปิดงานแล้วต้องให้ผู้จัดการแก้ใน desk)
EDITABLE_STATUSES = {"Draft", "In Progress", "On Hold"}

# ตรงกับ options ของฟิลด์ fuel_level_in / fuel_level_out
FUEL_LEVELS = ("หมด", "1/4", "ครึ่ง", "3/4", "เต็ม")

# เปลี่ยนสถานะได้เฉพาะเส้นทางเหล่านี้ (Draft → In Progress ต้องผ่านการรับรถ)
ALLOWED_TRANSITIONS = {
	"Draft": {"In Progress"},
	"In Progress": {"On Hold", "Completed"},
	"On Hold": {"In Progress"},
	"Completed": set(),
	"Cancelled": set(),
}

# เพดานกันค่าพิมพ์ผิด
MAX_ACTUAL_TIME = 999.0
MAX_MILEAGE = 9999999.0


def _is_assigned(doc, user):
	return any(doc.get(fieldname) == user for fieldname in TECHNICIAN_FIELDS)


def _get_editable_job(service_order):
	"""โหลดใบงานพร้อมตรวจสิทธิ์ครบทุกชั้น — ทุก endpoint ต้องเรียกผ่านตัวนี้"""
	doc = frappe.get_doc("Service Order", service_order)

	# ชั้นที่ 1 — สิทธิ์ write ระดับ doctype
	doc.check_permission("write")

	# ชั้นที่ 2 — ต้องเป็นช่างในใบนี้จริง (ระดับ record ซึ่ง doctype permission ยังไม่มี)
	if not _is_assigned(doc, frappe.session.user) and not (MANAGER_ROLES & set(frappe.get_roles())):
		frappe.throw(_("คุณไม่ได้เป็นช่างผู้รับผิดชอบใบสั่งงานนี้"), frappe.PermissionError)

	# ชั้นที่ 3 — แก้ได้เฉพาะเอกสารที่ยังไม่ submit และงานที่ยังไม่ปิด
	if doc.docstatus != 0:
		frappe.throw(_("ใบสั่งงานนี้ถูก submit หรือยกเลิกแล้ว ไม่สามารถแก้ไขจากพอร์ทัลได้"))

	if doc.status not in EDITABLE_STATUSES:
		frappe.throw(_("ใบสั่งงานสถานะ {0} ไม่สามารถแก้ไขจากพอร์ทัลได้").format(doc.status))

	return doc


@frappe.whitelist()
def set_fuel_level(service_order, which, value):
	"""บันทึกสถานะน้ำมันรับเข้า/ออก — which เป็น "in" หรือ "out" """
	if which not in ("in", "out"):
		frappe.throw(_("ระบุช่องน้ำมันไม่ถูกต้อง"))

	if value not in FUEL_LEVELS:
		frappe.throw(_("ระดับน้ำมันไม่ถูกต้อง"))

	doc = _get_editable_job(service_order)
	doc.set(f"fuel_level_{which}", value)
	doc.save()

	return {"value": value}


@frappe.whitelist()
def set_actual_time(service_order, hours):
	"""บันทึกเวลาทำงานจริง (ชั่วโมง) — ปุ่มลบ/บวก ฝั่งหน้าเว็บส่งค่าผลลัพธ์มาทั้งค่า"""
	hours = flt(hours, 2)
	if hours < 0 or hours > MAX_ACTUAL_TIME:
		frappe.throw(_("เวลาทำงานต้องอยู่ระหว่าง 0 ถึง {0} ชม.").format(cint(MAX_ACTUAL_TIME)))

	doc = _get_editable_job(service_order)
	doc.actual_time = hours
	doc.save()

	return {"value": hours}


@frappe.whitelist()
def set_mileage(service_order, mileage):
	"""บันทึกเลขไมล์ปัจจุบัน — ฟิลด์เดียวที่ยังต้องพิมพ์"""
	mileage = flt(mileage, 2)
	if mileage < 0 or mileage > MAX_MILEAGE:
		frappe.throw(_("เลขไมล์ไม่ถูกต้อง"))

	doc = _get_editable_job(service_order)
	doc.current_mileage = mileage
	doc.save()

	return {"value": mileage}


@frappe.whitelist()
def set_remarks(service_order, remarks):
	"""บันทึกหมายเหตุช่าง

	ฟิลด์ปลายทางเป็น Text Editor (เก็บ HTML) แต่พอร์ทัลรับมาเป็นข้อความล้วน
	จึง escape แล้วแปลงบรรทัดใหม่เป็น <br> เพื่อกัน HTML แปลกปลอมหลุดเข้า desk
	"""
	remarks = (remarks or "").strip()
	if len(remarks) > 2000:
		frappe.throw(_("หมายเหตุยาวเกินไป (สูงสุด 2000 ตัวอักษร)"))

	doc = _get_editable_job(service_order)
	doc.technician_remarks = escape_html(remarks).replace("\n", "<br>") if remarks else None
	doc.save()

	return {"value": remarks}


@frappe.whitelist()
def set_status(service_order, status):
	"""เปลี่ยนสถานะงานตามเส้นทางที่อนุญาตเท่านั้น

	Draft → In Progress ส่งต่อให้ receive_vehicle ของ controller เดิม
	เพื่อให้ยัง stamp ผู้รับรถ/เวลา และบังคับกรอกน้ำมันรับเข้าเหมือนทำผ่าน desk
	"""
	doc = _get_editable_job(service_order)

	if status not in ALLOWED_TRANSITIONS.get(doc.status, set()):
		frappe.throw(
			_("เปลี่ยนสถานะจาก {0} เป็น {1} ไม่ได้").format(doc.status, status),
			title=_("ไม่สามารถเปลี่ยนสถานะได้"),
		)

	if doc.status == "Draft" and status == "In Progress":
		receive_vehicle(doc.name)
	else:
		doc.status = status
		doc.save()

	return {"value": status}

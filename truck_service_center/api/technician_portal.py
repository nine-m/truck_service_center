# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""API สำหรับพอร์ทัลช่าง (/service-order-portal)

เปิดเฉพาะสิ่งที่ช่างต้องแก้หน้างานจริง ไม่ได้เปิด doctype ทั้งใบ
ทุก endpoint ตรวจ 3 ชั้น: สิทธิ์ write ของ doctype → ต้องเป็นช่างในใบนั้น → เอกสารต้องยังเป็น draft
"""

import frappe
from frappe import _
from frappe.utils import escape_html, flt, now_datetime

from truck_service_center.queries import get_technician_users
from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	ROW_TECHNICIAN_FIELDS,
	create_material_issue_for_rows,
	get_bay_warnings,
	receive_vehicle,
	select_requisition_rows,
)

# ช่องช่างผู้รับผิดชอบทั้ง 10 ช่องของ Service Order (แบน ไม่ใช่ child table)
TECHNICIAN_FIELDS = ("technician", *(f"technician_{i}" for i in range(2, 11)))

# role ที่ดูแลงานช่างได้ทุกใบ ไม่ต้องถูกระบุชื่อในใบงาน
MANAGER_ROLES = {"Technician Manager", "Service Manager", "System Manager"}

# สถานะที่ยังให้แก้ข้อมูลจากพอร์ทัลได้ (ปิดงานแล้วต้องให้ผู้จัดการแก้ใน desk)
EDITABLE_STATUSES = {"Draft", "In Progress", "On Hold"}

# ตรงกับ options ของฟิลด์ fuel_level_in / fuel_level_out
FUEL_LEVELS = ("หมด", "1/4", "ครึ่ง", "3/4", "เต็ม")

# เปลี่ยนสถานะได้เฉพาะเส้นทางเหล่านี้ (Draft → In Progress ต้องผ่านการรับรถ)
ALLOWED_TRANSITIONS = {
	"Draft": {"In Progress"},
	"In Progress": {"On Hold", "Ready for Delivery"},
	"On Hold": {"In Progress"},
	"Ready for Delivery": set(),
	"Completed": set(),
	"Cancelled": set(),
}

# เพดานกันค่าพิมพ์ผิด
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


def _is_manager():
	return bool(MANAGER_ROLES & set(frappe.get_roles()))


def _get_manager_job(service_order):
	"""ใบงานที่หัวหน้าช่างเท่านั้นแก้ได้ — ใช้กับ assign/unassign/reset

	ผ่าน _get_editable_job ก่อนเสมอ เพื่อให้ยังได้ด่านครบทั้ง 3 ชั้นเหมือน endpoint อื่น
	แล้วค่อยบวกเงื่อนไข role ทับอีกชั้น
	"""
	doc = _get_editable_job(service_order)

	if not _is_manager():
		frappe.throw(_("เฉพาะหัวหน้าช่างเท่านั้นที่ทำรายการนี้ได้"), frappe.PermissionError)

	return doc


def _get_service_row(doc, row_name):
	"""หาแถวงานด้วย name ของแถว — ห้ามใช้ index เพราะเลื่อนได้เมื่อมีการลบแถว"""
	for row in doc.service_types:
		if row.name == row_name:
			return row

	frappe.throw(_("ไม่พบรายการงานที่ระบุในใบสั่งงานนี้"))


def _user_on_row(row, user):
	return any(row.get(fieldname) == user for fieldname in ROW_TECHNICIAN_FIELDS)


def _get_row_job(service_order, row_name):
	"""ใบงาน + แถวงาน สำหรับช่างที่ถูก assign ในแถวนั้น (หรือหัวหน้าช่าง)

	ละเอียดกว่า _get_editable_job หนึ่งขั้น — ช่างที่อยู่ในใบงานแต่ไม่ได้รับงานรายการนี้
	จะกดเริ่ม/จบ/เบิกอะไหล่ของรายการนั้นไม่ได้
	"""
	doc = _get_editable_job(service_order)
	row = _get_service_row(doc, row_name)

	if not _user_on_row(row, frappe.session.user) and not _is_manager():
		frappe.throw(_("คุณไม่ได้รับผิดชอบงานรายการนี้"), frappe.PermissionError)

	return doc, row


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


# ══════════ งานราย service ══════════


@frappe.whitelist()
def assign_technician(service_order, row_name, user):
	"""หัวหน้าช่าง assign ช่างลงงานรายการหนึ่ง

	assign ได้ตั้งแต่ Draft เพื่อให้วางแผนงานล่วงหน้าก่อนรับรถได้
	ไม่ต้องเติมช่างขึ้นระดับใบงานเอง — sync_row_technicians_to_parent ใน validate ทำให้แล้ว
	"""
	doc = _get_manager_job(service_order)
	row = _get_service_row(doc, row_name)

	if user not in get_technician_users():
		frappe.throw(_("ผู้ใช้ {0} ไม่ได้เป็นช่าง").format(user))

	if _user_on_row(row, user):
		return {"value": user}

	free = next((f for f in ROW_TECHNICIAN_FIELDS if not row.get(f)), None)
	if not free:
		frappe.throw(_("งานรายการนี้มีช่างครบ {0} คนแล้ว").format(len(ROW_TECHNICIAN_FIELDS)))

	row.set(free, user)
	doc.save()

	return {"value": user}


@frappe.whitelist()
def unassign_technician(service_order, row_name, user):
	"""ถอนช่างออกจากงานรายการหนึ่ง แล้วเลื่อนช่างที่เหลือขึ้นให้ช่องว่างไปอยู่ท้ายเสมอ

	ไม่ลบช่างออกจากระดับใบงาน เพราะเขาอาจยังรับงานรายการอื่นอยู่ และ sync เป็นทางเดียว
	"""
	doc = _get_manager_job(service_order)
	row = _get_service_row(doc, row_name)

	remaining = [row.get(f) for f in ROW_TECHNICIAN_FIELDS if row.get(f) and row.get(f) != user]

	for fieldname in ROW_TECHNICIAN_FIELDS:
		row.set(fieldname, None)
	for fieldname, remaining_user in zip(ROW_TECHNICIAN_FIELDS, remaining, strict=False):
		row.set(fieldname, remaining_user)

	doc.save()

	return {"value": user}


@frappe.whitelist()
def start_service(service_order, row_name):
	"""ช่างกดเริ่มงานรายการหนึ่ง — stamp เวลาเริ่ม

	ต้องรับรถก่อน (ใบงานต้องเป็น In Progress) เพราะสถานะใบงานไม่ได้ถูก drive
	จากปุ่มรายงาน แต่มาจากการรับรถตามเดิม
	"""
	doc, row = _get_row_job(service_order, row_name)

	if doc.status != "In Progress":
		frappe.throw(_("ต้องรับรถเข้าซ่อมก่อนจึงจะเริ่มงานได้"))

	if row.start_time:
		frappe.throw(_("งานรายการนี้เริ่มไปแล้ว"))

	row.start_time = now_datetime()
	doc.save()

	return {"value": str(row.start_time)}


@frappe.whitelist()
def finish_service(service_order, row_name):
	"""ช่างกดจบงานรายการหนึ่ง — stamp เวลาจบ แล้ว actual_time จะถูกคำนวณใหม่ใน validate"""
	doc, row = _get_row_job(service_order, row_name)

	if not row.start_time:
		frappe.throw(_("ต้องกดเริ่มงานก่อนจึงจะจบงานได้"))

	if row.end_time:
		frappe.throw(_("งานรายการนี้จบไปแล้ว"))

	row.end_time = now_datetime()
	doc.save()

	return {"value": str(row.end_time)}


@frappe.whitelist()
def reset_service(service_order, row_name):
	"""หัวหน้าช่างล้างเวลาเริ่ม-จบ เพื่อเปิดงานรายการนั้นใหม่

	เป็นทางเดียวที่แก้เวลาที่กดผิดได้ เพราะ actual_time เป็น read-only ทุกที่แล้ว
	"""
	doc = _get_manager_job(service_order)
	row = _get_service_row(doc, row_name)

	row.start_time = None
	row.end_time = None
	doc.save()

	return {"value": row.name}


# ══════════ ช่องจอด ══════════


def _validate_bay(service_bay):
	"""ช่องจอดต้องมีอยู่จริงและเปิดใช้งาน — ค่าว่างแปลว่าเคลียร์"""
	service_bay = (service_bay or "").strip()
	if not service_bay:
		return None

	if not frappe.db.get_value("Service Bay", service_bay, "is_active"):
		frappe.throw(_("ช่องจอด {0} ไม่มีอยู่หรือถูกปิดใช้งานแล้ว").format(service_bay))

	return service_bay


@frappe.whitelist()
def set_main_bay(service_order, service_bay=None):
	"""ตั้งช่องจอดหลักของใบงาน — แถวที่ยังไม่ระบุช่องจอดจะถูกเติมให้ใน validate"""
	doc = _get_editable_job(service_order)
	doc.service_bay = _validate_bay(service_bay)
	doc.save()

	return {"value": doc.service_bay or "", "warnings": get_bay_warnings(doc)}


@frappe.whitelist()
def set_service_bay(service_order, row_name, service_bay=None):
	"""ตั้งช่องจอดของงานรายการหนึ่ง — ค่าว่างจะตกไปใช้ช่องจอดหลักตอน validate"""
	doc = _get_editable_job(service_order)
	row = _get_service_row(doc, row_name)

	row.service_bay = _validate_bay(service_bay)
	doc.save()

	return {"value": row.service_bay or "", "warnings": get_bay_warnings(doc)}


# ══════════ ใบเบิกอะไหล่รายงาน ══════════


@frappe.whitelist()
def create_service_requisition(service_order, row_name):
	"""สร้างใบเบิกอะไหล่ของงานรายการหนึ่งจากพอร์ทัล

	role Technician ไม่มีสิทธิ์สร้าง Stock Entry จึงต้องส่ง ignore_permissions ลงไป
	ด่านจริงคือ _get_row_job ด้านบน (ต้องเป็นช่างของงานรายการนี้หรือหัวหน้าช่าง)
	ส่วนกฎ "ต้องรับรถก่อน" ยังถูกบังคับอยู่ภายใน create_material_issue_for_rows
	การแก้ไขใบเบิกหลังสร้างแล้วยังต้องทำผ่าน desk ตามเดิม
	"""
	doc, row = _get_row_job(service_order, row_name)

	rows = select_requisition_rows(doc, row)
	if not rows:
		frappe.throw(_("ไม่มีอะไหล่ที่ยังไม่ได้เบิกสำหรับงานนี้"))

	material_issue = create_material_issue_for_rows(doc, rows, ignore_permissions=True)

	return {"value": material_issue}


def _validate_completion(doc):
	"""ข้อมูลที่ช่างต้องบันทึกให้ครบก่อนปิดงาน — รวบฟ้องทีเดียวจะได้ไม่ต้องแก้หลายรอบ

	เวลาทำงานจริงเป็นเงื่อนไข submit อยู่แล้ว (Service Order.before_submit) แต่ต้องดัก
	ตั้งแต่ปิดงาน เพราะ Ready for Delivery หลุดจาก EDITABLE_STATUSES ช่างจึงกลับมาแก้ไม่ได้อีก
	ส่วนน้ำมันนำส่งเป็นคู่ของน้ำมันรับเข้าที่ receive_vehicle บังคับไว้ตอนรับรถ

	งานทุกรายการต้องกดจบแล้ว เพราะเวลาจบเป็นตัวคำนวณ actual_time ให้เอง
	ยังคงเช็ค actual_time > 0 ไว้ด้วยเพื่อกันเคสใบเก่า/ข้อมูลแปลกที่ไม่มี timestamp
	"""
	missing = []

	if flt(doc.actual_time) <= 0:
		missing.append(_("เวลาทำงานจริง (ต้องมากกว่า 0 ชม.)"))

	if not doc.fuel_level_out:
		missing.append(_("สถานะน้ำมันนำส่ง"))

	unfinished = [row.service_type or _("(ไม่ระบุ)") for row in doc.service_types if not row.end_time]
	if unfinished:
		missing.append(_("กดจบงานให้ครบทุกรายการ — ยังไม่จบ: {0}").format(", ".join(unfinished)))

	if missing:
		frappe.throw(
			_("กรุณาบันทึกข้อมูลต่อไปนี้ก่อนปิดงาน") + "<br>" + "<br>".join(f"• {label}" for label in missing),
			title=_("ข้อมูลไม่ครบ"),
		)


@frappe.whitelist()
def set_status(service_order, status):
	"""เปลี่ยนสถานะงานตามเส้นทางที่อนุญาตเท่านั้น

	Draft → In Progress ส่งต่อให้ receive_vehicle ของ controller เดิม
	เพื่อให้ยัง stamp ผู้รับรถ/เวลา และบังคับกรอกน้ำมันรับเข้าเหมือนทำผ่าน desk

	→ Ready for Delivery (ปิดงาน) ต้องผ่าน _validate_completion ก่อน (ด่านจริง — ฝั่งหน้าเว็บเตือนให้
	เฉย ๆ) ส่วนเลขไมล์ที่ยังไม่อัปเดตเป็นแค่คำเตือน จึงถามยืนยันที่ฝั่งหน้าเว็บอย่างเดียว
	"""
	doc = _get_editable_job(service_order)

	if status not in ALLOWED_TRANSITIONS.get(doc.status, set()):
		frappe.throw(
			_("เปลี่ยนสถานะจาก {0} เป็น {1} ไม่ได้").format(doc.status, status),
			title=_("ไม่สามารถเปลี่ยนสถานะได้"),
		)

	if status == "Ready for Delivery":
		_validate_completion(doc)

	if doc.status == "Draft" and status == "In Progress":
		receive_vehicle(doc.name)
	else:
		doc.status = status
		doc.save()

	return {"value": status}

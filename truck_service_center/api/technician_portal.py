# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""API สำหรับพอร์ทัลช่าง (/service-order-portal)

เปิดเฉพาะสิ่งที่ช่างต้องแก้หน้างานจริง ไม่ได้เปิด doctype ทั้งใบ
ทุก endpoint ตรวจ 3 ชั้น: สิทธิ์ write ของ doctype → ต้องเป็นช่างในใบนั้น → เอกสารต้องยังเป็น draft
ชั้นกลางของ endpoint ระดับแถวงานยอมให้หัวหน้างานของกลุ่มบริการของแถวนั้นผ่านด้วย
(เหมือนหัวหน้าช่าง แต่ขอบเขตแค่กลุ่มที่ตั้งไว้ใน Service Type Group.supervisors)
"""

import frappe
from frappe import _
from frappe.utils import escape_html, flt, now_datetime

from truck_service_center.branches import filter_users_by_branch
from truck_service_center.queries import get_technician_users
from truck_service_center.truck_service_center.doctype.parts_return.parts_return import (
	RETURN_APPROVED,
	RETURN_PENDING,
	RETURN_REJECTED,
	apply_parts_return,
	create_parts_return,
	stamp_return_decision,
)
from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	APPROVAL_APPROVED,
	APPROVAL_PENDING,
	APPROVAL_REJECTED,
	ROW_TECHNICIAN_FIELDS,
	can_approve_requisition,
	collect_material_issue_problems,
	create_material_issue_for_rows,
	get_bay_warnings,
	get_default_parts_warehouse,
	get_supervised_groups,
	receive_vehicle,
	select_group_requisition_rows,
	stamp_requisition_decision,
	sync_material_issue_status,
)
from truck_service_center.truck_service_center.doctype.service_type_group.service_type_group import (
	APPROVER_FALLBACK_ROLES,
)

# ช่องช่างผู้รับผิดชอบทั้ง 10 ช่องของ Service Order (แบน ไม่ใช่ child table)
TECHNICIAN_FIELDS = ("technician", *(f"technician_{i}" for i in range(2, 11)))

# role ที่ดูแลงานช่างได้ทุกใบ ไม่ต้องถูกระบุชื่อในใบงาน
MANAGER_ROLES = {"Technician Manager", "Service Manager", "System Manager"}

# สถานะที่ยังให้แก้ข้อมูลจากพอร์ทัลได้ (ปิดงานแล้วต้องให้ผู้จัดการแก้ใน desk)
EDITABLE_STATUSES = {"Draft", "In Progress", "On Hold"}

# ตรงกับ options ของฟิลด์ fuel_level_in / fuel_level_out
# NOT CHECK = ไม่ได้ตรวจระดับน้ำมัน — นับเป็นค่าที่บันทึกแล้ว ผ่านด่านรับรถ/ปิดงาน/submit ได้
FUEL_NOT_CHECKED = "NOT CHECK"
FUEL_LEVELS = ("หมด", "1/4", "ครึ่ง", "3/4", "เต็ม", FUEL_NOT_CHECKED)

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

# ฟอร์มขอเบิกอะไหล่เพิ่ม — ค้นเมื่อพิมพ์อย่างน้อย 2 ตัว คืนไม่เกิน 20 รายการ
SEARCH_MIN_CHARS = 2
SEARCH_LIMIT = 20
# เพดานกันพิมพ์ผิด/ยิงผิด: จำนวนต่อรายการ, จำนวนรายการต่อครั้ง, ความยาวเหตุผลที่ขอเบิก
MAX_PART_QTY = 999.0
MAX_REQUEST_LINES = 30
MAX_REQUEST_NOTE = 500


def _is_assigned(doc, user):
	return any(doc.get(fieldname) == user for fieldname in TECHNICIAN_FIELDS)


def _load_job(service_order):
	"""ชั้นที่ 1 — สิทธิ์ write ระดับ doctype"""
	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("write")
	return doc


def _ensure_open(doc):
	"""ชั้นที่ 3 — แก้ได้เฉพาะเอกสารที่ยังไม่ submit และงานที่ยังไม่ปิด"""
	if doc.docstatus != 0:
		frappe.throw(_("ใบสั่งงานนี้ถูก submit หรือยกเลิกแล้ว ไม่สามารถแก้ไขจากพอร์ทัลได้"))

	if doc.status not in EDITABLE_STATUSES:
		frappe.throw(_("ใบสั่งงานสถานะ {0} ไม่สามารถแก้ไขจากพอร์ทัลได้").format(doc.status))


def _has_job_access(doc):
	"""ชั้นที่ 2 ระดับใบงาน — เป็นช่างในใบนี้ หรือเป็นหัวหน้าช่าง/ผู้จัดการ"""
	return _is_assigned(doc, frappe.session.user) or _is_manager()


def _get_editable_job(service_order):
	"""ใบงานสำหรับ endpoint ระดับใบ (น้ำมัน ไมล์ หมายเหตุ สถานะ ช่องจอดหลัก)

	หัวหน้างานกลุ่มที่ไม่ได้อยู่ในใบงานผ่านด่านนี้ไม่ได้ — ขอบเขตของเขาคือแถวงานในกลุ่ม
	ไม่ใช่ทั้งใบ (ถ้า assign ตัวเองลงแถวงาน ก็จะกลายเป็นช่างในใบและผ่านได้เอง)
	"""
	doc = _load_job(service_order)

	# ชั้นที่ 2 — ต้องเป็นช่างในใบนี้จริง (ระดับ record ซึ่ง doctype permission ยังไม่มี)
	if not _has_job_access(doc):
		frappe.throw(_("คุณไม่ได้เป็นช่างผู้รับผิดชอบใบสั่งงานนี้"), frappe.PermissionError)

	_ensure_open(doc)
	return doc


def _is_manager():
	return bool(MANAGER_ROLES & set(frappe.get_roles()))


def _can_manage_row(row, supervised_groups=None):
	"""จัดการแถวงานนี้แบบหัวหน้าได้ไหม (assign/ถอนช่าง, เริ่มใหม่, ช่องจอดรายแถว)

	หัวหน้าช่าง/ผู้จัดการได้ทุกแถว หัวหน้างานกลุ่มได้เฉพาะแถวที่ service_type_group
	อยู่ในกลุ่มที่ตัวเองดูแล — แถวที่ไม่มีกลุ่มจึงเป็นของหัวหน้าช่างเท่านั้น
	"""
	if _is_manager():
		return True

	if supervised_groups is None:
		supervised_groups = get_supervised_groups()
	return bool(row.service_type_group) and row.service_type_group in supervised_groups


def _get_row_manager_job(service_order, row_name):
	"""ใบงาน + แถวงาน สำหรับงานระดับหัวหน้า (assign/unassign/reset)

	ผ่านครบ 3 ชั้นเหมือน endpoint อื่น แต่ชั้นกลางเป็น _can_manage_row แทนการเป็นช่างในใบ
	"""
	doc = _load_job(service_order)
	row = _get_service_row(doc, row_name)

	if not _can_manage_row(row):
		frappe.throw(
			_("เฉพาะหัวหน้าช่าง หรือหัวหน้างานของกลุ่มบริการของงานนี้เท่านั้นที่ทำรายการนี้ได้"),
			frappe.PermissionError,
		)

	_ensure_open(doc)
	return doc, row


def _get_service_row(doc, row_name):
	"""หาแถวงานด้วย name ของแถว — ห้ามใช้ index เพราะเลื่อนได้เมื่อมีการลบแถว"""
	for row in doc.service_types:
		if row.name == row_name:
			return row

	frappe.throw(_("ไม่พบรายการงานที่ระบุในใบสั่งงานนี้"))


def _user_on_row(row, user):
	return any(row.get(fieldname) == user for fieldname in ROW_TECHNICIAN_FIELDS)


def _get_row_job(service_order, row_name):
	"""ใบงาน + แถวงาน สำหรับช่างที่ถูก assign ในแถวนั้น (หรือหัวหน้าช่าง / หัวหน้างานของกลุ่มแถวนั้น)

	ละเอียดกว่า _get_editable_job หนึ่งขั้น — ช่างที่อยู่ในใบงานแต่ไม่ได้รับงานรายการนี้
	จะกดเริ่ม/จบ/เบิกอะไหล่ของรายการนั้นไม่ได้
	"""
	doc = _load_job(service_order)
	row = _get_service_row(doc, row_name)

	if not _user_on_row(row, frappe.session.user) and not _can_manage_row(row):
		frappe.throw(_("คุณไม่ได้รับผิดชอบงานรายการนี้"), frappe.PermissionError)

	_ensure_open(doc)
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
	"""หัวหน้าช่าง (หรือหัวหน้างานของกลุ่มงานนั้น) assign ช่างลงงานรายการหนึ่ง

	assign ได้ตั้งแต่ Draft เพื่อให้วางแผนงานล่วงหน้าก่อนรับรถได้
	ไม่ต้องเติมช่างขึ้นระดับใบงานเอง — sync_row_technicians_to_parent ใน validate ทำให้แล้ว
	"""
	doc, row = _get_row_manager_job(service_order, row_name)

	if user not in get_technician_users():
		frappe.throw(_("ผู้ใช้ {0} ไม่ได้เป็นช่าง").format(user))
	if not filter_users_by_branch([user], doc.branch):
		frappe.throw(_("ช่าง {0} ไม่ได้อยู่สาขา {1}").format(user, doc.branch))

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
	doc, row = _get_row_manager_job(service_order, row_name)

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
	# ช่างไม่มีสิทธิ์แก้เวลาในฟอร์ม แต่ stamp จากปุ่มนี้ได้ (ดู validate_work_times)
	doc.flags.allow_work_time_stamp = True
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
	# ช่างไม่มีสิทธิ์แก้เวลาในฟอร์ม แต่ stamp จากปุ่มนี้ได้ (ดู validate_work_times)
	doc.flags.allow_work_time_stamp = True
	doc.save()

	return {"value": str(row.end_time)}


@frappe.whitelist()
def reset_service(service_order, row_name):
	"""หัวหน้าช่างล้างเวลาเริ่ม-จบ เพื่อเปิดงานรายการนั้นใหม่

	ในพอร์ทัลเป็นทางเดียวที่แก้เวลาที่กดผิดได้ — ใน desk หัวหน้าช่างแก้เวลาในแถวงานเองได้ด้วย
	"""
	doc, row = _get_row_manager_job(service_order, row_name)

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
	"""ตั้งช่องจอดของงานรายการหนึ่ง — ค่าว่างจะตกไปใช้ช่องจอดหลักตอน validate

	ช่างในใบ / หัวหน้าช่าง / หัวหน้างานของกลุ่มแถวนั้น
	"""
	doc = _load_job(service_order)
	row = _get_service_row(doc, row_name)

	if not _has_job_access(doc) and not _can_manage_row(row):
		frappe.throw(_("คุณไม่ได้รับผิดชอบงานรายการนี้"), frappe.PermissionError)

	_ensure_open(doc)

	row.service_bay = _validate_bay(service_bay)
	doc.save()

	return {"value": row.service_bay or "", "warnings": get_bay_warnings(doc)}


# ══════════ ใบเบิกอะไหล่รายกลุ่มบริการ + การอนุมัติ ══════════

# เหตุผลไม่อนุมัติยาวสุดเท่านี้ — เป็นข้อความสั้นให้ช่างรู้ว่าต้องแก้อะไร ไม่ใช่รายงาน
MAX_REJECTION_REASON = 500


def _get_group_job(service_order, service_type_group):
	"""ใบงานสำหรับขออนุมัติเบิกอะไหล่ของกลุ่มบริการหนึ่ง

	กลุ่มที่มีชื่อ: ช่างต้องอยู่บนแถวงานอย่างน้อยหนึ่งแถวในกลุ่มนั้น (หรือเป็นหัวหน้าช่าง /
	หัวหน้างานของกลุ่มนั้น) — เกณฑ์เดียวกับ _get_row_job เพียงขยายจาก "แถวนี้" เป็น "แถวใดแถวหนึ่งในกลุ่ม"
	กลุ่มว่าง (อะไหล่อื่น ๆ / งานไม่มีกลุ่ม) ไม่ผูกกับแถวไหนแน่นอน จึงใช้สิทธิ์ระดับใบ
	เหมือนกลุ่ม "อะไหล่อื่น ๆ" เดิม
	"""
	if not service_type_group:
		return _get_editable_job(service_order)

	doc = _load_job(service_order)

	if not _is_manager() and service_type_group not in get_supervised_groups():
		rows = [row for row in doc.service_types if row.service_type_group == service_type_group]
		if not any(_user_on_row(row, frappe.session.user) for row in rows):
			frappe.throw(_("คุณไม่ได้รับผิดชอบงานในกลุ่มบริการนี้"), frappe.PermissionError)

	_ensure_open(doc)
	return doc


@frappe.whitelist()
def create_group_requisition(service_order, service_type_group=None, note=None):
	"""ขออนุมัติเบิกอะไหล่จากพอร์ทัล — หนึ่งใบต่อกลุ่มบริการ

	งานหลายรายการที่อยู่กลุ่มเดียวกันรวมเป็นใบเดียว เพราะผู้อนุมัติผูกกับกลุ่ม
	ใบเกิดเป็น Stock Entry Draft สถานะ "รออนุมัติ" — สต๊อก submit ไม่ได้จนกว่าหัวหน้างานกลุ่ม
	(หรือหัวหน้าช่าง/ผู้จัดการ) จะอนุมัติ ส่วนผู้ขอที่อนุมัติกลุ่มนั้นได้เองจะถูกอนุมัติให้ทันที

	role Technician ไม่มีสิทธิ์สร้าง Stock Entry จึงต้องส่ง ignore_permissions ลงไป
	ด่านจริงคือ _get_group_job ส่วนกฎ "ต้องรับรถก่อน" ยังถูกบังคับใน create_material_issue_for_rows

	note = เหตุผลที่ขอ (ไม่บังคับ) เก็บลง Stock Entry.remarks ให้ผู้อนุมัติเห็นบนการ์ดใบเบิก
	"""
	service_type_group = service_type_group or None
	doc = _get_group_job(service_order, service_type_group)

	rows = select_group_requisition_rows(doc, service_type_group)
	if not rows:
		frappe.throw(_("ไม่มีอะไหล่ที่ยังไม่ได้เบิกในกลุ่มนี้"))

	material_issue = create_material_issue_for_rows(
		doc, rows, ignore_permissions=True, service_type_group=service_type_group
	)

	note = (note or "").strip()[:MAX_REQUEST_NOTE]
	if note:
		# ใบเบิกถูกสร้างด้วย ignore_permissions — ช่างไม่มีสิทธิ์ Stock Entry จึงเขียนตรง
		frappe.db.set_value("Stock Entry", material_issue, "remarks", note)

	return {
		"value": material_issue,
		"approval_status": frappe.db.get_value("Stock Entry", material_issue, "custom_approval_status"),
	}


@frappe.whitelist()
def search_parts(service_order, txt=None):
	"""ค้นอะไหล่สำหรับฟอร์มขอเบิกเพิ่ม — รหัส / ชื่อ / บาร์โค้ด (ตรงตัว) พร้อมยอดคงเหลือในคลังเบิก

	role Technician ไม่มีสิทธิ์อ่าน Item จึงใช้ frappe.get_all โดยเจตนา ขอบเขตคือ
	ต้องเปิดใบสั่งงานนั้นได้ และคืนเฉพาะสินค้าคงคลังที่ยังใช้งาน (ของที่เบิกได้จริงเท่านั้น)
	ไม่คืนราคา — ราคาเป็นเรื่องของ desk (calculate_totals เติม rate ให้ตอนบันทึก)
	"""
	frappe.has_permission("Service Order", "read", service_order, throw=True)

	txt = (txt or "").strip()
	if len(txt) < SEARCH_MIN_CHARS:
		return []

	filters = {"disabled": 0, "is_stock_item": 1, "has_variants": 0}
	fields = ["name", "item_name", "stock_uom"]

	# สแกนบาร์โค้ดเข้ามา (เครื่องสแกนพิมพ์ตัวเลขแล้วกด Enter) — ตรงตัวขึ้นก่อนเสมอ
	barcode_items = frappe.get_all("Item Barcode", filters={"barcode": txt}, pluck="parent", limit=5)
	exact = frappe.get_all(
		"Item", filters={**filters, "name": ["in", [txt, *barcode_items]]}, fields=fields, limit=5
	)
	like = f"%{txt}%"
	rows = exact + [
		row
		for row in frappe.get_all(
			"Item",
			filters=filters,
			or_filters={"name": ["like", like], "item_name": ["like", like]},
			fields=fields,
			order_by="item_name asc",
			limit=SEARCH_LIMIT,
		)
		if row.name not in {item.name for item in exact}
	]
	rows = rows[:SEARCH_LIMIT]

	warehouse = get_default_parts_warehouse(frappe.db.get_value("Service Order", service_order, "branch"))
	stock = {}
	if warehouse and rows:
		stock = dict(
			frappe.get_all(
				"Bin",
				filters={"warehouse": warehouse, "item_code": ["in", [row.name for row in rows]]},
				fields=["item_code", "actual_qty"],
				as_list=True,
			)
		)

	return [
		{
			"item_code": row.name,
			"item_name": row.item_name or row.name,
			"uom": row.stock_uom or "",
			"actual_qty": flt(stock.get(row.name)) if warehouse else None,
			"exact": index < len(exact),
		}
		for index, row in enumerate(rows)
	]


def _parse_requested_parts(parts):
	"""[{item_code, qty}] จาก client → รายการที่ตรวจแล้ว รวมรหัสซ้ำเป็นแถวเดียว

	ด่านเดียวกับ search_parts: ต้องเป็นสินค้าคงคลังที่ยังใช้งาน — ของนอกสต๊อกเบิกไม่ได้อยู่แล้ว
	(create_material_issue_for_rows จะข้ามแถวนั้น) ถ้าปล่อยเข้ามาจะกลายเป็นแถวที่ไม่มีวันมีใบเบิก
	"""
	parts = frappe.parse_json(parts) if isinstance(parts, str) else parts
	if not isinstance(parts, list) or not parts:
		frappe.throw(_("กรุณาเลือกอะไหล่อย่างน้อยหนึ่งรายการ"))
	if len(parts) > MAX_REQUEST_LINES:
		frappe.throw(_("ขอเบิกได้ครั้งละไม่เกิน {0} รายการ").format(MAX_REQUEST_LINES))

	merged = {}
	for part in parts:
		code = (part or {}).get("item_code")
		qty = flt((part or {}).get("qty"))
		if not code:
			continue
		if qty <= 0 or qty > MAX_PART_QTY:
			frappe.throw(_("จำนวนของ {0} ต้องมากกว่า 0 และไม่เกิน {1}").format(code, MAX_PART_QTY))
		merged[code] = merged.get(code, 0) + qty

	if not merged:
		frappe.throw(_("กรุณาเลือกอะไหล่อย่างน้อยหนึ่งรายการ"))

	valid = set(
		frappe.get_all(
			"Item",
			filters={"name": ["in", list(merged)], "disabled": 0, "is_stock_item": 1, "has_variants": 0},
			pluck="name",
		)
	)
	invalid = [code for code in merged if code not in valid]
	if invalid:
		frappe.throw(_("อะไหล่ต่อไปนี้เบิกไม่ได้ (ไม่ใช่สินค้าคงคลัง หรือถูกปิดใช้งาน): {0}").format(", ".join(invalid)))

	return merged


@frappe.whitelist()
def add_parts(service_order, parts, service_row=None):
	"""ช่างคีย์อะไหล่ที่ต้องเบิกเพิ่มลงใบสั่งงาน — เพิ่มแถวอย่างเดียว ยังไม่สร้างใบเบิก

	ใบเบิกเกิดตอนกด "ขออนุมัติเบิก" ของกลุ่ม (create_group_requisition) ซึ่งรวมอะไหล่ค้างเบิกทั้งกลุ่ม
	เป็นใบเดียว — ถ้าสร้างใบตรงนี้เลย ของที่ค้างอยู่ก่อนในกลุ่มเดียวกันจะต้องแยกไปอีกใบ
	(ผู้อนุมัติกดสองรอบ สต๊อก submit สองใบ ทั้งที่เป็นงานเดียวกัน)

	แถวใหม่รับ provenance (service_type + service_package) จากงานที่เลือก
	get_item_service_type_group จึงจัดเข้ากลุ่มของงานนั้น และ cascade ตามงานนั้นเหมือนอะไหล่ของงาน
	ไม่เลือกงาน = กลุ่ม "อะไหล่อื่น ๆ / ไม่มีกลุ่ม" ซึ่งหัวหน้าช่าง/ผู้จัดการอนุมัติ

	สิทธิ์: _get_group_job ตัวเดียวกับปุ่มขออนุมัติเบิกรายกลุ่ม — คนที่เพิ่มได้คือคนที่ขออนุมัติกลุ่มนั้นได้
	"""
	service_type_group = None
	if service_row:
		# อ่านกลุ่มก่อนโหลดใบ เพราะด่านสิทธิ์ (_get_group_job) ขึ้นกับกลุ่ม
		service_type_group = frappe.db.get_value(
			"Service Order Service Type",
			{"parent": service_order, "parenttype": "Service Order", "name": service_row},
			"service_type_group",
		)
	doc = _get_group_job(service_order, service_type_group or None)
	row = _get_service_row(doc, service_row) if service_row else None

	# อะไหล่ที่เพิ่มต้องเบิกต่อได้ทันที — กฎเดียวกับ create_material_issue_for_rows
	if not doc.received_date and doc.status != "In Progress":
		frappe.throw(_("ยังไม่ได้รับรถเข้าซ่อม กรุณารับรถก่อนเพิ่มอะไหล่"))

	merged = _parse_requested_parts(parts)
	warehouse = get_default_parts_warehouse(doc.branch)

	for code, qty in merged.items():
		doc.append(
			"service_items",
			{
				"item_code": code,
				"qty": qty,
				"warehouse": warehouse,
				"service_type": row.service_type if row else None,
				"service_package": row.service_package if row else None,
				"requested_by": frappe.session.user,
			},
		)
	doc.save()

	return {"added": len(merged)}


@frappe.whitelist()
def remove_requested_part(service_order, item_row):
	"""ลบแถวอะไหล่ที่ช่างขอเพิ่มเองจากพอร์ทัล — คีย์ผิดก่อนขออนุมัติ หรือหลังใบเบิกถูกไม่อนุมัติ

	ลบได้เฉพาะแถวที่มี requested_by และยังไม่มีใบเบิกผูกอยู่ โดยคนที่ขอเอง หรือหัวหน้าช่าง/ผู้จัดการ
	แถวที่มาจาก desk / แพ็คเกจ / ประเภทบริการ ลบจากพอร์ทัลไม่ได้ ต้องแก้ใน desk
	"""
	doc = _load_job(service_order)
	item = next((line for line in doc.service_items if line.name == item_row), None)
	if not item:
		frappe.throw(_("ไม่พบรายการอะไหล่ที่ระบุในใบสั่งงานนี้"))

	if not item.get("requested_by"):
		frappe.throw(_("ลบได้เฉพาะอะไหล่ที่ขอเพิ่มจากพอร์ทัลเท่านั้น"), frappe.PermissionError)
	if item.requested_by != frappe.session.user and not _is_manager():
		frappe.throw(_("ลบได้เฉพาะอะไหล่ที่คุณขอเพิ่มเอง"), frappe.PermissionError)
	if item.material_issue:
		frappe.throw(_("อะไหล่นี้มีใบเบิก {0} อยู่ ลบไม่ได้").format(item.material_issue))

	_ensure_open(doc)

	doc.remove(item)
	doc.save()
	return {"removed": item_row}


def _get_pending_requisition(stock_entry):
	"""ใบเบิกที่ผู้ใช้ปัจจุบันพิจารณาได้ — ต้องเป็นใบของใบสั่งงาน, Draft, รออนุมัติ และเป็นผู้อนุมัติ

	ล็อกแถว (for_update) กันสองคนกดพร้อมกันแล้วได้ผลซ้อน
	ไม่ตรวจสิทธิ์ doctype ของ Stock Entry — หัวหน้างานกลุ่มไม่มีสิทธิ์ Stock Entry เลย
	ด่านจริงคือ can_approve_requisition
	"""
	if not frappe.db.exists("Stock Entry", stock_entry):
		frappe.throw(_("ไม่พบใบเบิก {0}").format(stock_entry))

	doc = frappe.get_doc("Stock Entry", stock_entry, for_update=True)

	if not doc.get("custom_service_order"):
		frappe.throw(_("{0} ไม่ใช่ใบเบิกอะไหล่ของใบสั่งงาน").format(doc.name))

	if doc.docstatus != 0:
		frappe.throw(_("ใบเบิก {0} ถูก submit หรือยกเลิกไปแล้ว").format(doc.name))

	if doc.get("custom_approval_status") != APPROVAL_PENDING:
		frappe.throw(_("ใบเบิก {0} ไม่ได้อยู่ในสถานะรออนุมัติแล้ว").format(doc.name))

	if not can_approve_requisition(doc):
		frappe.throw(_("คุณไม่ใช่ผู้อนุมัติใบเบิกของกลุ่มบริการนี้"), frappe.PermissionError)

	return doc


def _record_decision(stock_entry, status, reason=None):
	"""บันทึกผลพิจารณา + ซิงค์สถานะลงแถวอะไหล่ + ทิ้ง comment ไว้ทั้งสองเอกสาร

	ใช้ db_set ไม่ใช่ save — ใบเบิกอาจถูกสต๊อกแก้จำนวนค้างไว้ และผู้อนุมัติไม่มีสิทธิ์ Stock Entry
	"""
	values = stamp_requisition_decision(stock_entry, status, reason=reason)
	stock_entry.db_set(values)

	# ไม่อนุมัติ → sync ปลด link ออกจากแถวอะไหล่ ช่างจะได้แก้แล้วขอเบิกใหม่ได้
	# (ใบ Rejected ค้างไว้เป็นหลักฐาน และ submit ไม่ได้เพราะ validate_requisition_approved)
	sync_material_issue_status(stock_entry.name, 0)

	who = values["custom_approved_by_name"]
	if status == APPROVAL_APPROVED:
		text = _("อนุมัติใบเบิกอะไหล่ {0} โดย {1}").format(stock_entry.name, who)
	else:
		text = _("ไม่อนุมัติใบเบิกอะไหล่ {0} โดย {1} — เหตุผล: {2}").format(
			stock_entry.name, who, escape_html(reason)
		)

	stock_entry.add_comment("Info", text)
	frappe.get_doc("Service Order", stock_entry.custom_service_order).add_comment("Info", text)

	return {"value": status, "approved_by_name": who}


@frappe.whitelist()
def approve_requisition(stock_entry):
	"""หัวหน้างานกลุ่ม (หรือหัวหน้าช่าง/ผู้จัดการ) อนุมัติใบเบิก — สต๊อกจึง submit ได้"""
	doc = _get_pending_requisition(stock_entry)
	return _record_decision(doc, APPROVAL_APPROVED)


@frappe.whitelist()
def reject_requisition(stock_entry, reason=None):
	"""ไม่อนุมัติใบเบิก — ต้องระบุเหตุผล แถวอะไหล่ถูกปลด link ให้ช่างขอเบิกใหม่ได้"""
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("กรุณาระบุเหตุผลที่ไม่อนุมัติ"))
	if len(reason) > MAX_REJECTION_REASON:
		frappe.throw(_("เหตุผลยาวเกินไป (สูงสุด {0} ตัวอักษร)").format(MAX_REJECTION_REASON))

	doc = _get_pending_requisition(stock_entry)
	return _record_decision(doc, APPROVAL_REJECTED, reason=reason)


@frappe.whitelist()
def get_requisition_actions(stock_entry):
	"""ปุ่มอนุมัติ/ไม่อนุมัติบนฟอร์ม Stock Entry (desk) ควรขึ้นหรือไม่ — ด่านจริงอยู่ที่ endpoint ข้างบน"""
	values = frappe.db.get_value(
		"Stock Entry",
		stock_entry,
		["docstatus", "custom_service_order", "custom_approval_status", "custom_service_type_group"],
		as_dict=True,
	)
	if not values:
		return {"can_approve": False}

	pending = (
		values.docstatus == 0
		and values.custom_service_order
		and values.custom_approval_status == APPROVAL_PENDING
	)
	return {"can_approve": bool(pending) and can_approve_requisition(values)}


@frappe.whitelist()
def request_parts_return(service_order, stock_entry, lines, reason=None):
	"""ช่างขอคืนอะไหล่ที่เบิกแล้วไม่ได้ใช้ — คืนบางส่วนได้ (lines = {ชื่อแถวอะไหล่: จำนวนคืน})

	หนึ่งใบคืนต่อหนึ่งใบเบิก ผู้อนุมัติชุดเดียวกับใบเบิกนั้น ผู้ขอที่อนุมัติกลุ่มนั้นได้เอง
	(หัวหน้าช่าง/ผู้จัดการ/หัวหน้างานของกลุ่ม) ถูกอนุมัติให้ทันที เหมือนตอนสร้างใบเบิก
	สิทธิ์ขอ: _get_group_job ของกลุ่มใบเบิก — คนที่ขอเบิกกลุ่มนั้นได้ก็ขอคืนได้
	"""
	if not frappe.db.exists("Stock Entry", stock_entry):
		frappe.throw(_("ไม่พบใบเบิก {0}").format(stock_entry))
	entry = frappe.get_doc("Stock Entry", stock_entry)
	if entry.get("custom_service_order") != service_order:
		frappe.throw(_("{0} ไม่ใช่ใบเบิกของใบสั่งงานนี้").format(stock_entry))

	doc = _get_group_job(service_order, entry.get("custom_service_type_group") or None)

	requested = frappe.parse_json(lines) if isinstance(lines, str) else lines
	if not isinstance(requested, dict):
		frappe.throw(_("รูปแบบรายการคืนไม่ถูกต้อง"))
	reason = (reason or "").strip()[:MAX_REQUEST_NOTE]

	parts_return = create_parts_return(doc, entry, requested, reason=reason)
	frappe.get_doc("Service Order", doc.name).add_comment(
		"Info",
		_("ขอคืนอะไหล่ {0} จากใบเบิก {1} ยอด {2} บาท").format(
			parts_return.name, entry.name, parts_return.total_amount
		),
	)

	if can_approve_requisition(entry):
		stamp_return_decision(parts_return, RETURN_APPROVED)
		apply_parts_return(parts_return)

	return {"value": parts_return.name, "approval_status": parts_return.approval_status}


def _get_pending_return(name):
	"""ใบคืนที่ผู้ใช้ปัจจุบันพิจารณาได้ — รออนุมัติอยู่ และเป็นผู้อนุมัติของใบเบิกต้นทาง

	ล็อกแถว (for_update) กันสองคนกดพร้อมกัน ใบเบิกต้นทางถูกลบไปแล้ว (มีคนลบมือบน desk)
	ยังไม่อนุมัติได้ด้วย fallback roles จะได้ไม่มีใบค้างตลอดไป
	"""
	if not frappe.db.exists("Parts Return", name):
		frappe.throw(_("ไม่พบใบคืนอะไหล่ {0}").format(name))

	doc = frappe.get_doc("Parts Return", name, for_update=True)
	if doc.approval_status != RETURN_PENDING:
		frappe.throw(_("ใบคืน {0} ไม่ได้อยู่ในสถานะรออนุมัติแล้ว").format(doc.name))

	if frappe.db.exists("Stock Entry", doc.stock_entry):
		allowed = can_approve_requisition(frappe.get_doc("Stock Entry", doc.stock_entry))
	else:
		allowed = bool(APPROVER_FALLBACK_ROLES & set(frappe.get_roles()))
	if not allowed:
		frappe.throw(_("คุณไม่ใช่ผู้อนุมัติของกลุ่มบริการนี้"), frappe.PermissionError)

	return doc


@frappe.whitelist()
def approve_parts_return(parts_return):
	"""อนุมัติใบคืน → ลดจำนวนในใบเบิกและใบสั่งงาน + อัปเดตยอดอะไหล่ที่คืน"""
	doc = _get_pending_return(parts_return)
	stamp_return_decision(doc, RETURN_APPROVED)
	apply_parts_return(doc)

	text = _("อนุมัติใบคืนอะไหล่ {0} โดย {1} — ยอดคืน {2} บาท").format(
		doc.name, doc.approved_by_name, doc.total_amount
	)
	frappe.get_doc("Service Order", doc.service_order).add_comment("Info", text)
	return {"value": RETURN_APPROVED, "total_amount": doc.total_amount}


@frappe.whitelist()
def reject_parts_return(parts_return, reason=None):
	"""ไม่อนุมัติใบคืน — ต้องมีเหตุผล จำนวนในใบเบิก/ใบสั่งงานไม่เปลี่ยน"""
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("กรุณาระบุเหตุผลที่ไม่อนุมัติ"))

	doc = _get_pending_return(parts_return)
	stamp_return_decision(doc, RETURN_REJECTED, reason=reason)
	doc.save(ignore_permissions=True)

	text = _("ไม่อนุมัติใบคืนอะไหล่ {0} โดย {1} — เหตุผล: {2}").format(
		doc.name, doc.approved_by_name, escape_html(reason)
	)
	frappe.get_doc("Service Order", doc.service_order).add_comment("Info", text)
	return {"value": RETURN_REJECTED}


def _get_pending_return_names(service_order):
	return frappe.get_all(
		"Parts Return",
		filters={"service_order": service_order, "approval_status": RETURN_PENDING},
		pluck="name",
	)


def _validate_completion(doc):
	"""ข้อมูลที่ช่างต้องบันทึกให้ครบก่อนปิดงาน — รวบฟ้องทีเดียวจะได้ไม่ต้องแก้หลายรอบ

	เวลาทำงานจริงเป็นเงื่อนไข submit อยู่แล้ว (Service Order.before_submit) แต่ต้องดัก
	ตั้งแต่ปิดงาน เพราะ Ready for Delivery หลุดจาก EDITABLE_STATUSES ช่างจึงกลับมาแก้ไม่ได้อีก
	ส่วนน้ำมันนำส่งเป็นคู่ของน้ำมันรับเข้าที่ receive_vehicle บังคับไว้ตอนรับรถ

	งานทุกรายการต้องกดจบแล้ว เพราะเวลาจบเป็นตัวคำนวณ actual_time ให้เอง
	ยังคงเช็ค actual_time > 0 ไว้ด้วยเพื่อกันเคสใบเก่า/ข้อมูลแปลกที่ไม่มี timestamp

	อะไหล่ทุกแถวที่เป็นสินค้าคงคลังต้องมีใบเบิกแล้ว — เดิมกฎนี้อยู่ที่ submit เท่านั้น
	(Service Order.validate_material_issues_for_submit) ช่างจึงปิดงานทั้งที่ยังไม่เบิกได้
	แล้วของก็ออกจากคลังไม่ครบ พอปิดงานแล้วสถานะหลุด EDITABLE_STATUSES กลับมาเบิกเองก็ไม่ได้
	"""
	missing = []

	if flt(doc.actual_time) <= 0:
		missing.append(_("เวลาทำงานจริง (ต้องมากกว่า 0 ชม.)"))

	if not doc.fuel_level_out:
		missing.append(_("สถานะน้ำมันนำส่ง"))

	unfinished = [row.service_type or _("(ไม่ระบุ)") for row in doc.service_types if not row.end_time]
	if unfinished:
		missing.append(_("กดจบงานให้ครบทุกรายการ — ยังไม่จบ: {0}").format(", ".join(unfinished)))

	# ตรวจแค่ว่า "มีใบเบิกแล้ว" ไม่ได้ตรวจว่า submit แล้ว — ใบเบิกที่สร้างจากพอร์ทัลเป็น Draft
	# เสมอ (role Technician submit Stock Entry ไม่ได้) การ submit ยังเป็นงานของผู้จัดการบน desk
	unissued = collect_material_issue_problems(doc)["items_without_mi"]
	if unissued:
		missing.append(
			_("สร้างใบเบิกอะไหล่ให้ครบ — ยังไม่ได้เบิก: {0}").format(", ".join(row["label"] for row in unissued))
		)

	# ปิดงานแล้วสต๊อก submit ใบเบิกได้ทันที — ใบคืนที่ค้างจะทำให้จำนวนที่ออกจากคลังผิด
	# ใบที่ยังไม่บันทึกไม่มีใบคืนแน่นอน (และเทสต์ที่ stub frappe.db ก็ไม่ต้องแตะตารางนี้)
	pending_returns = [] if doc.is_new() else _get_pending_return_names(doc.name)
	if pending_returns:
		missing.append(_("รอหัวหน้างานพิจารณาใบคืนอะไหล่ให้เสร็จก่อน: {0}").format(", ".join(pending_returns)))

	if missing:
		frappe.throw(
			_("กรุณาบันทึกข้อมูลต่อไปนี้ก่อนปิดงาน") + "<br>" + "<br>".join(f"• {label}" for label in missing),
			title=_("ข้อมูลไม่ครบ"),
		)


@frappe.whitelist()
def set_status(service_order, status):
	"""เปลี่ยนสถานะงานตามเส้นทางที่อนุญาตเท่านั้น — ใช้ทั้งพอร์ทัลและปุ่มในฟอร์ม desk

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
		# สถานะถูกล็อกไม่ให้เลือกเอง (validate_status_change) — endpoint นี้คือทางที่อนุญาต
		doc.flags.allow_status_change = True
		doc.save()

	return {"value": status}

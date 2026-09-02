# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""พอร์ทัลช่าง — หน้ารายละเอียดใบสั่งงานหนึ่งใบ

route: /service-order-portal/<name> (ผูกไว้ใน hooks.website_route_rules)
แสดงเฉพาะข้อมูลที่ช่างต้องใช้หน้างาน และให้แก้ไขผ่านปุ่มเป็นหลัก
การบันทึกทั้งหมดวิ่งผ่าน truck_service_center.api.technician_portal
"""

from html import unescape

import frappe
from frappe import _
from frappe.utils import flt, format_datetime, now_datetime, strip_html

from truck_service_center.api.technician_portal import (
	ALLOWED_TRANSITIONS,
	EDITABLE_STATUSES,
	FUEL_LEVELS,
	MANAGER_ROLES,
	TECHNICIAN_FIELDS,
)
from truck_service_center.www.service_order_portal import (
	PRIORITY_LABELS,
	STATUS_LABELS,
	STATUS_THEMES,
)

no_cache = 1

# ปุ่มเปลี่ยนสถานะ: สถานะปลายทาง -> (ข้อความบนปุ่ม, สไตล์)
STATUS_ACTIONS = {
	"In Progress": ("เริ่มงาน / ทำงานต่อ", "primary"),
	"On Hold": ("พักงาน", "secondary"),
	"Completed": ("ปิดงาน", "success"),
}

# ปุ่มเปลี่ยนสถานะจาก Draft สื่อความหมายว่า "รับรถ" มากกว่า "เริ่มงาน"
RECEIVE_LABEL = "รับรถเข้าซ่อม"

# ชิปหมายเหตุที่ช่างกดใส่ได้เลย ไม่ต้องพิมพ์
REMARK_PRESETS = (
	"ตรวจสอบแล้ว ปกติ",
	"เปลี่ยนอะไหล่เรียบร้อย",
	"ทดสอบการทำงานแล้ว ปกติ",
	"ต้องสั่งอะไหล่เพิ่ม",
	"รอลูกค้าอนุมัติ",
	"แนะนำให้ตรวจเช็คครั้งถัดไป",
)


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(_("You need to be logged in to access this page"), frappe.PermissionError)

	name = frappe.form_dict.get("name")
	if not name or not frappe.db.exists("Service Order", name):
		raise frappe.DoesNotExistError

	doc = frappe.get_doc("Service Order", name)
	doc.check_permission("read")

	is_manager = bool(MANAGER_ROLES & set(frappe.get_roles()))
	is_assigned = any(doc.get(fieldname) == frappe.session.user for fieldname in TECHNICIAN_FIELDS)
	if not is_assigned and not is_manager:
		frappe.throw(_("คุณไม่ได้เป็นช่างผู้รับผิดชอบใบสั่งงานนี้"), frappe.PermissionError)

	# บังคับให้มี csrf token ในหน้า เพื่อให้ frappe.call ยิง POST ได้
	frappe.sessions.get_csrf_token()

	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True
	context.title = doc.name
	context.fetched_at = format_datetime(now_datetime(), "HH:mm")

	context.doc = doc
	context.job = _build_job_view(doc)
	context.fuel_levels = FUEL_LEVELS
	context.remark_presets = REMARK_PRESETS

	# แก้ไขได้ก็ต่อเมื่อยังไม่ submit และงานยังไม่ปิด — ตรงกับที่ api บังคับไว้
	context.editable = doc.docstatus == 0 and doc.status in EDITABLE_STATUSES
	context.status_actions = _build_status_actions(doc)

	return context


def _build_job_view(doc):
	"""ดึงเฉพาะฟิลด์ที่ช่างต้องใช้ พร้อม format ให้เรียบร้อยตั้งแต่ฝั่ง python"""
	return frappe._dict(
		name=doc.name,
		status=doc.status,
		status_label=STATUS_LABELS.get(doc.status) or doc.status,
		status_theme=STATUS_THEMES.get(doc.status, "grey"),
		priority_label=PRIORITY_LABELS.get(doc.priority) or doc.priority,
		# truck_number เป็น fetch_from ที่ยังว่างในข้อมูลเดิมส่วนใหญ่ → ใช้ชื่อรถ (= ทะเบียน) แทน
		truck_label=doc.truck_number or doc.vehicle or "-",
		vehicle_spec=" ".join(filter(None, [doc.brand, doc.model])) or "-",
		vehicle_type=doc.vehicle_type or "-",
		vin_number=doc.vin_number or "-",
		customer=doc.customer or "-",
		contact_person=doc.contact_person or "-",
		contact_number=doc.contact_number or "",
		service_date_label=format_datetime(doc.service_date, "dd/MM/yyyy HH:mm") if doc.service_date else "-",
		complaints=_plain_text(doc.customer_complaints),
		remarks=_plain_text(doc.technician_remarks),
		fuel_level_in=doc.fuel_level_in or "",
		fuel_level_out=doc.fuel_level_out or "",
		actual_time=_num(doc.actual_time),
		estimated_time=_num(doc.estimated_time),
		current_mileage=_num(doc.current_mileage),
		packages=[
			frappe._dict(
				label=row.package_name or row.package_code or row.service_package,
				code=row.service_package,
			)
			for row in doc.service_packages
		],
		service_types=[
			frappe._dict(
				label=row.service_type,
				package=row.service_package or "",
				position=row.repair_position or "",
				estimated_time=_num(row.estimated_time),
				remark=_plain_text(row.remark),
			)
			for row in doc.service_types
		],
		# ห้ามตั้งชื่อ key ว่า items — frappe._dict เป็น dict ทำให้ job.items ไปเจอเมธอด dict.items
		parts=[
			frappe._dict(
				label=row.item_name or row.item_code,
				package=row.service_package or "",
				qty=_num(row.qty),
				uom=row.uom or "",
				issued=(row.material_issue_status or "") == "Issued",
			)
			for row in doc.service_items
		],
	)


def _build_status_actions(doc):
	"""ปุ่มเปลี่ยนสถานะที่กดได้จริงจากสถานะปัจจุบัน"""
	actions = []
	for target in ALLOWED_TRANSITIONS.get(doc.status, set()):
		label, variant = STATUS_ACTIONS[target]
		if doc.status == "Draft" and target == "In Progress":
			label = RECEIVE_LABEL
		actions.append(frappe._dict(status=target, label=label, variant=variant))

	# เรียงให้ปุ่มเดินหน้า (เริ่ม/ปิดงาน) มาก่อนปุ่มพักงานเสมอ
	actions.sort(key=lambda a: a.status == "On Hold")
	return actions


def _num(value):
	"""ตัด .0 ท้ายเลขจำนวนเต็ม ให้ค่าที่ render ตรงกับที่ JS ของ stepper แสดง"""
	number = flt(value, 2)
	return int(number) if number == int(number) else number


def _plain_text(value):
	"""ฟิลด์ Text Editor เก็บ HTML — แปลงกลับเป็นข้อความล้วนสำหรับแสดงและใส่ใน textarea"""
	if not value:
		return ""

	text = value.replace("<br>", "\n").replace("<br/>", "\n").replace("</p>", "\n")
	return unescape(strip_html(text)).strip()

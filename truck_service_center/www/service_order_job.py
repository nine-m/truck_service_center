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
from truck_service_center.queries import get_technician_users
from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	ROW_TECHNICIAN_FIELDS,
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
	"Ready for Delivery": ("ปิดงาน (รอส่งมอบรถ)", "success"),
}

# ปุ่มเปลี่ยนสถานะจาก Draft สื่อความหมายว่า "รับรถ" มากกว่า "เริ่มงาน"
RECEIVE_LABEL = "รับรถเข้าซ่อม"

# สถานะงานรายการ derive จาก timestamp ล้วน ๆ ไม่ได้เก็บในแถว จึงไม่มีทาง drift
SERVICE_STATE_LABELS = {
	"pending": "รอเริ่ม",
	"running": "กำลังทำ",
	"done": "เสร็จแล้ว",
}

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
	context.job = _build_job_view(doc, is_manager)
	context.fuel_levels = FUEL_LEVELS
	context.remark_presets = REMARK_PRESETS

	# แก้ไขได้ก็ต่อเมื่อยังไม่ submit และงานยังไม่ปิด — ตรงกับที่ api บังคับไว้
	context.editable = doc.docstatus == 0 and doc.status in EDITABLE_STATUSES
	context.status_actions = _build_status_actions(doc)

	# หัวหน้าช่างเห็นปุ่ม assign ช่าง / เริ่มงานใหม่ ที่ช่างธรรมดาไม่เห็น
	context.is_manager = is_manager

	# ช่องจอดที่เลือกได้ — render ฝั่ง server จึงไม่ต้องเปิด endpoint list เพิ่ม
	context.bays = frappe.get_all(
		"Service Bay",
		filters={"is_active": 1},
		fields=["name", "bay_name", "has_pit"],
		order_by="bay_name asc",
	)

	# รายชื่อช่างสำหรับ dropdown assign — เฉพาะหัวหน้าช่างเท่านั้นที่ต้องใช้
	context.technician_options = _get_technician_options() if is_manager else []

	return context


def _get_technician_options():
	"""ช่างทั้งหมดพร้อมชื่อเต็ม สำหรับ dropdown assign ของหัวหน้าช่าง"""
	users = get_technician_users()
	if not users:
		return []

	rows = frappe.get_all(
		"User",
		filters={"name": ["in", users], "enabled": 1},
		fields=["name", "full_name"],
		order_by="full_name asc",
	)
	return [frappe._dict(user=row.name, label=row.full_name or row.name) for row in rows]


def _build_job_view(doc, is_manager=False):
	"""ดึงเฉพาะฟิลด์ที่ช่างต้องใช้ พร้อม format ให้เรียบร้อยตั้งแต่ฝั่ง python"""
	# เลขไมล์ที่ผูกกับรถอยู่ คือค่าที่ระบบเติมให้ตอนสร้างใบงาน (service_order.js / service_appointment.py)
	# หน้าเว็บใช้เทียบว่าช่างอัปเดตเลขไมล์ของงานนี้แล้วหรือยัง เพื่อถามยืนยันตอนปิดงาน
	vehicle_mileage = frappe.db.get_value("Vehicle", doc.vehicle, "current_mileage") if doc.vehicle else None

	service_types = _build_service_rows(doc, is_manager)
	parts = _build_parts(doc)

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
		vehicle_mileage=_num(vehicle_mileage) if vehicle_mileage else None,
		packages=[
			frappe._dict(
				label=row.package_name or row.package_code or row.service_package,
				code=row.service_package,
			)
			for row in doc.service_packages
		],
		service_bay=doc.service_bay or "",
		service_types=service_types,
		# ห้ามตั้งชื่อ key ว่า items — frappe._dict เป็น dict ทำให้ job.items ไปเจอเมธอด dict.items
		parts=parts,
		part_groups=_group_parts(service_types, parts),
	)


def _build_service_rows(doc, is_manager):
	"""แถวงานพร้อมสถานะที่ derive จาก timestamp และสิทธิ์กดปุ่มของ user ปัจจุบัน"""
	user = frappe.session.user
	full_names = _get_full_names(
		{row.get(f) for row in doc.service_types for f in ROW_TECHNICIAN_FIELDS if row.get(f)}
	)

	rows = []
	for row in doc.service_types:
		# ไม่มี start = รอเริ่ม, มี start = กำลังทำ, มี end = เสร็จแล้ว
		if row.end_time:
			state = "done"
		elif row.start_time:
			state = "running"
		else:
			state = "pending"

		technicians = [
			frappe._dict(user=row.get(f), label=full_names.get(row.get(f)) or row.get(f))
			for f in ROW_TECHNICIAN_FIELDS
			if row.get(f)
		]
		mine = any(tech.user == user for tech in technicians)
		allowed = mine or is_manager

		rows.append(
			frappe._dict(
				name=row.name,
				label=row.service_type,
				package=row.service_package or "",
				position=row.repair_position or "",
				estimated_time=_num(row.estimated_time),
				remark=_plain_text(row.remark),
				service_bay=row.service_bay or "",
				technicians=technicians,
				state=state,
				state_label=SERVICE_STATE_LABELS[state],
				start_label=format_datetime(row.start_time, "dd/MM HH:mm") if row.start_time else "",
				end_label=format_datetime(row.end_time, "dd/MM HH:mm") if row.end_time else "",
				# ปุ่มเริ่มโผล่เฉพาะตอนรับรถแล้ว — สถานะใบงานไม่ได้ถูก drive จากปุ่มรายงาน
				can_start=allowed and state == "pending" and doc.status == "In Progress",
				can_finish=allowed and state == "running",
			)
		)

	return rows


def _build_parts(doc):
	"""แถวอะไหล่ + provenance ที่ใช้จัดกลุ่มใต้แต่ละงาน และสถานะใบเบิกที่ถูกต้อง"""
	return [
		frappe._dict(
			label=row.item_name or row.item_code,
			package=row.service_package or "",
			service_type=row.service_type or "",
			qty=_num(row.qty),
			uom=row.uom or "",
			# controller เขียนค่านี้เป็น Draft/Submitted/Cancelled เท่านั้น — เทียบกับ
			# "Issued" ที่เคยใช้อยู่จึงไม่เคยเป็นจริงเลย ป้าย "เบิกแล้ว" จึงไม่เคยขึ้น
			issued=(row.material_issue_status or "") == "Submitted",
			material_issue=row.material_issue or "",
		)
		for row in doc.service_items
	]


def _group_parts(service_types, parts):
	"""จัดกลุ่มอะไหล่ใต้งานที่มันถูกดึงมา เพื่อให้ช่างกดสร้างใบเบิกทีละงานได้

	จับคู่ด้วยค่า service_type (+ service_package ถ้าแถวงานมี) ชุดเดียวกับ
	select_requisition_rows ฝั่ง server จะได้ไม่แสดงคนละอย่างกับที่จะถูกเบิกจริง
	อะไหล่ที่ไม่มี service_type คือของที่เพิ่มเอง ไปรวมกันที่กลุ่มท้ายสุด
	"""
	groups = []
	claimed = set()

	for row in service_types:
		members = []
		for idx, part in enumerate(parts):
			if idx in claimed or not part.service_type:
				continue
			if part.service_type != row.label:
				continue
			if row.package and part.package != row.package:
				continue
			claimed.add(idx)
			members.append(part)

		if members:
			groups.append(
				frappe._dict(
					row_name=row.name,
					label=row.label,
					parts=members,
					# ปุ่มสร้างใบเบิกซ่อนเมื่อเบิกครบแล้ว
					pending=sum(1 for part in members if not part.material_issue),
					# เลขใบเบิกของกลุ่ม — ปกติมีใบเดียว แต่เบิกหลายรอบได้จึงเป็น list
					issues=sorted({part.material_issue for part in members if part.material_issue}),
				)
			)

	leftovers = [part for idx, part in enumerate(parts) if idx not in claimed]
	if leftovers:
		groups.append(
			frappe._dict(
				row_name="",
				label="อะไหล่อื่น ๆ",
				parts=leftovers,
				pending=0,
				issues=sorted({part.material_issue for part in leftovers if part.material_issue}),
			)
		)

	return groups


def _get_full_names(users):
	"""ดึงชื่อเต็มทีเดียวเป็น batch กัน N+1 ตอน render ช่างหลายคนหลายแถว"""
	users = {user for user in users if user}
	if not users:
		return {}

	rows = frappe.get_all("User", filters={"name": ["in", list(users)]}, fields=["name", "full_name"])
	return {row.name: row.full_name for row in rows}


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

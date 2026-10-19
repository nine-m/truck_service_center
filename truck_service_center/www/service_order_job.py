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
	APPROVAL_APPROVED,
	APPROVAL_PENDING,
	APPROVAL_REJECTED,
	ROW_TECHNICIAN_FIELDS,
	get_item_service_type_group,
	get_supervised_groups,
)
from truck_service_center.truck_service_center.doctype.service_type_group.service_type_group import (
	APPROVER_FALLBACK_ROLES,
)
from truck_service_center.www.service_order_portal import (
	NO_GROUP_LABEL,
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

# สถานะใบเบิก → (ข้อความ, สีป้าย data-state) — ใบเก่าไม่มีสถานะอนุมัติ ถือว่าผ่านแล้ว
REQUISITION_STATES = {
	APPROVAL_PENDING: ("รออนุมัติ", "running"),
	APPROVAL_APPROVED: ("อนุมัติแล้ว รอสต๊อก submit", "approved"),
	APPROVAL_REJECTED: ("ไม่อนุมัติ", "rejected"),
	"": ("รอสต๊อก submit", "approved"),
	"submitted": ("เบิกแล้ว", "done"),
}

# เหตุผลไม่อนุมัติสำเร็จรูป — หัวหน้างานแตะแล้วแก้ต่อได้
REJECT_PRESETS = (
	"จำนวนเกินที่ใช้จริง",
	"ผิดรายการ / ผิดรุ่น",
	"ยังมีของเหลือในรถ",
	"ให้ตรวจสอบอาการก่อนเบิก",
)

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

	roles = set(frappe.get_roles())
	is_manager = bool(MANAGER_ROLES & roles)
	is_assigned = any(doc.get(fieldname) == frappe.session.user for fieldname in TECHNICIAN_FIELDS)
	supervised_groups = get_supervised_groups()

	# หัวหน้างานกลุ่มที่ไม่ได้ถูก assign เปิดได้เมื่อใบนี้มีงานในกลุ่มที่ตัวเองดูแล (จัดการได้เฉพาะแถว
	# ในกลุ่ม + ปุ่มอนุมัติ ข้อมูลระดับใบดูได้อย่างเดียว) หรือมีใบเบิกในกลุ่มนั้น — นับใบเบิกที่ตัดสิน
	# ไปแล้วด้วย ไม่งั้นแถวงานถูกลบหลังอนุมัติแล้ว reload จะเจอหน้า Not Permitted
	supervisor_view = False
	if not is_assigned and not is_manager:
		in_scope = any(row.service_type_group in supervised_groups for row in doc.service_types)
		if not in_scope and not _has_requisition_in_groups(doc.name, supervised_groups):
			frappe.throw(_("คุณไม่ได้เป็นช่างผู้รับผิดชอบใบสั่งงานนี้"), frappe.PermissionError)
		supervisor_view = True

	# doc_open = เอกสารยังแก้ได้ (ตรงกับ _ensure_open ของ api) ส่วน editable = แก้ข้อมูลระดับใบได้
	# หัวหน้างานกลุ่มที่ไม่ได้อยู่ในใบ แก้ได้เฉพาะแถวงานในกลุ่มของตน (line.can_manage)
	doc_open = doc.docstatus == 0 and doc.status in EDITABLE_STATUSES

	# บังคับให้มี csrf token ในหน้า เพื่อให้ frappe.call ยิง POST ได้
	frappe.sessions.get_csrf_token()

	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True
	context.title = doc.name
	context.fetched_at = format_datetime(now_datetime(), "HH:mm")

	context.doc = doc
	context.job = _build_job_view(
		doc,
		is_manager,
		approver=frappe._dict(is_fallback=bool(APPROVER_FALLBACK_ROLES & roles), groups=supervised_groups),
		doc_open=doc_open,
		job_access=not supervisor_view,
	)
	context.fuel_levels = FUEL_LEVELS
	context.remark_presets = REMARK_PRESETS
	context.reject_presets = REJECT_PRESETS

	# แก้ไขได้ก็ต่อเมื่อยังไม่ submit และงานยังไม่ปิด — ตรงกับที่ api บังคับไว้
	# หัวหน้างานกลุ่มที่ไม่ได้อยู่ในใบ แก้ข้อมูลระดับใบไม่ได้ (api ก็ไม่ให้อยู่แล้ว)
	context.doc_open = doc_open
	context.editable = doc_open and not supervisor_view
	context.supervisor_view = supervisor_view
	context.status_actions = _build_status_actions(doc)

	# หัวหน้าช่างเห็นปุ่ม assign ช่าง / เริ่มงานใหม่ ที่ช่างธรรมดาไม่เห็น
	context.is_manager = is_manager

	# ช่องจอดที่เลือกได้ — render ฝั่ง server จึงไม่ต้องเปิด endpoint list เพิ่ม
	# ชื่อประเภทมาจาก query เดียวแล้วแปะลงทุกแถว ไม่ใช่ lookup รายช่อง
	context.bays = frappe.get_all(
		"Service Bay",
		filters={"is_active": 1},
		fields=["name", "bay_name", "bay_type"],
		order_by="bay_name asc",
	)
	bay_type_names = {
		row.name: row.bay_type_name for row in frappe.get_all("Bay Type", fields=["name", "bay_type_name"])
	}
	for bay in context.bays:
		bay.bay_type_name = bay_type_names.get(bay.bay_type) or bay.bay_type

	# รายชื่อช่างสำหรับ dropdown assign — เฉพาะคนที่ assign ได้อย่างน้อยหนึ่งแถว
	can_assign = any(line.can_manage for line in context.job.service_types)
	context.technician_options = _get_technician_options() if can_assign else []

	return context


def _has_requisition_in_groups(service_order, groups):
	"""ใบสั่งงานนี้มีใบเบิก (ที่ยังไม่ถูกยกเลิก) ในกลุ่มบริการที่ระบุหรือไม่"""
	if not groups:
		return False

	return bool(
		frappe.db.exists(
			"Stock Entry",
			{
				"custom_service_order": service_order,
				"custom_service_type_group": ["in", list(groups)],
				"docstatus": ["<", 2],
			},
		)
	)


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


def _build_job_view(doc, is_manager=False, approver=None, doc_open=True, job_access=True):
	"""ดึงเฉพาะฟิลด์ที่ช่างต้องใช้ พร้อม format ให้เรียบร้อยตั้งแต่ฝั่ง python

	approver = _dict(is_fallback, groups) ของผู้ใช้ปัจจุบัน — ใช้ตัดสินปุ่มอนุมัติรายใบเบิก
	และ groups ชุดเดียวกันคือขอบเขตที่หัวหน้างานกลุ่มจัดการแถวงานได้
	job_access = เป็นช่างในใบ/หัวหน้าช่าง (False = หัวหน้างานกลุ่มที่เข้ามาจากขอบเขตกลุ่ม)
	"""
	approver = approver or frappe._dict(is_fallback=False, groups=set())
	# เลขไมล์ที่ผูกกับรถอยู่ คือค่าที่ระบบเติมให้ตอนสร้างใบงาน (service_order.js / service_appointment.py)
	# หน้าเว็บใช้เทียบว่าช่างอัปเดตเลขไมล์ของงานนี้แล้วหรือยัง เพื่อถามยืนยันตอนปิดงาน
	vehicle_mileage = frappe.db.get_value("Vehicle", doc.vehicle, "current_mileage") if doc.vehicle else None

	service_types = _build_service_rows(doc, is_manager, approver.groups, doc_open)
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
		part_groups=_group_parts(
			service_types,
			parts,
			group_names=_get_group_names({row.group for row in service_types} | {p.group for p in parts}),
			issues=_get_requisitions(doc, approver),
			is_manager=is_manager,
			supervised_groups=approver.groups,
			job_access=job_access,
		),
		# ชื่ออะไหล่ที่ยังไม่มีใบเบิก — หน้าเว็บใช้เตือนก่อนกดปิดงาน ด่านจริงคือ
		# _validate_completion ฝั่ง server
		unissued_parts=[part.label for part in parts if part.needs_issue],
	)


def _build_service_rows(doc, is_manager, supervised_groups=frozenset(), doc_open=True):
	"""แถวงานพร้อมสถานะที่ derive จาก timestamp และสิทธิ์กดปุ่มของ user ปัจจุบัน

	can_manage ตรงกับ _can_manage_row ของ api: หัวหน้าช่างทุกแถว หัวหน้างานกลุ่มเฉพาะแถวในกลุ่มตน
	"""
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
		manages = is_manager or (bool(row.service_type_group) and row.service_type_group in supervised_groups)
		allowed = mine or manages

		rows.append(
			frappe._dict(
				name=row.name,
				label=row.service_type,
				package=row.service_package or "",
				group=row.service_type_group or "",
				# ช่างของแถวนี้ — ปุ่มขออนุมัติเบิกของกลุ่มขึ้นให้คนที่อยู่บนแถวใดแถวหนึ่งในกลุ่ม
				mine=mine,
				# assign/ถอนช่าง, ช่องจอดรายแถว, เริ่มใหม่ — ต้องเป็นเอกสารที่ยังแก้ได้ด้วย
				can_manage=manages and doc_open,
				position=row.repair_position or "",
				estimated_time=_num(row.estimated_time),
				remark=_plain_text(row.remark),
				service_bay=row.service_bay or "",
				technicians=technicians,
				state=state,
				state_label=SERVICE_STATE_LABELS[state],
				start_label=format_datetime(row.start_time, "dd/MM HH:mm") if row.start_time else "",
				end_label=format_datetime(row.end_time, "dd/MM HH:mm") if row.end_time else "",
				# เวลาที่หัวหน้าช่างคีย์เองใน desk — โชว์ให้รู้ว่าไม่ได้มาจากปุ่ม
				manual_time=bool(row.time_manually_entered),
				# ปุ่มเริ่มโผล่เฉพาะตอนรับรถแล้ว — สถานะใบงานไม่ได้ถูก drive จากปุ่มรายงาน
				can_start=allowed and state == "pending" and doc.status == "In Progress",
				can_finish=allowed and state == "running",
			)
		)

	return rows


def _stock_item_codes(doc):
	"""item_code ของอะไหล่ที่เป็นสินค้าคงคลัง — ดึงทีเดียวกัน N+1 ตอน render หลายแถว"""
	codes = {row.item_code for row in doc.service_items if row.item_code}
	if not codes:
		return set()

	return set(
		frappe.get_all("Item", filters={"name": ["in", list(codes)], "is_stock_item": 1}, pluck="name")
	)


def _build_parts(doc):
	"""แถวอะไหล่ + provenance ที่ใช้จัดกลุ่มใต้แต่ละงาน และสถานะใบเบิกที่ถูกต้อง"""
	stock_items = _stock_item_codes(doc)

	return [
		frappe._dict(
			label=row.item_name or row.item_code,
			package=row.service_package or "",
			service_type=row.service_type or "",
			# กลุ่มบริการของแถวอะไหล่ — เกณฑ์เดียวกับที่ create_group_requisition ใช้เลือกแถว
			group=get_item_service_type_group(doc, row) or "",
			qty=_num(row.qty),
			uom=row.uom or "",
			# controller เขียนค่านี้เป็น Draft/Submitted/Cancelled เท่านั้น — เทียบกับ
			# "Issued" ที่เคยใช้อยู่จึงไม่เคยเป็นจริงเลย ป้าย "เบิกแล้ว" จึงไม่เคยขึ้น
			issued=(row.material_issue_status or "") == "Submitted",
			material_issue=row.material_issue or "",
			pending_approval=(row.material_issue_status or "") == "Pending Approval",
			# เฉพาะสินค้าคงคลังที่ต้องมีใบเบิก — ชุดเดียวกับที่ collect_material_issue_problems
			# กันไว้ตอน submit ค่าบริการ/อะไหล่นอกสต็อกไม่ต้องเบิกและเบิกไม่ได้ด้วย
			needs_issue=row.item_code in stock_items and not row.material_issue,
		)
		for row in doc.service_items
	]


def _group_parts(
	service_types,
	parts,
	group_names=None,
	issues=None,
	is_manager=False,
	supervised_groups=frozenset(),
	job_access=True,
):
	"""จัดกลุ่มอะไหล่ตามกลุ่มบริการ — หนึ่งกลุ่มคือใบขออนุมัติเบิกหนึ่งใบ

	กลุ่มของอะไหล่มาจาก part.group (get_item_service_type_group ฝั่ง server) จะได้แสดงตรงกับ
	ที่ create_group_requisition จะเบิกจริง อะไหล่ที่ไม่มีกลุ่ม (เพิ่มเอง / งานไม่มีกลุ่ม)
	ไปรวมกันที่กลุ่มท้ายสุด ซึ่งต้องเบิกได้เสมอ ไม่งั้นใบงานจะปิดไม่ได้

	issues = {ชื่อใบเบิก: _dict} จาก _get_requisitions — ใบที่ไม่อนุมัติถูกปลดออกจากแถวอะไหล่แล้ว
	จึงแนบตามกลุ่มของใบแทน และแสดงเฉพาะตอนกลุ่มยังมีของต้องขอใหม่ (เหตุผลยังมีประโยชน์)
	"""
	group_names = group_names or {}
	issues = issues or {}

	order = []
	for key in [row.group for row in service_types] + [part.group for part in parts]:
		if key and key not in order:
			order.append(key)
	order.append("")

	groups = []
	for key in order:
		members = [part for part in parts if part.group == key]
		if not members:
			continue

		pending = sum(1 for part in members if part.needs_issue)
		rows = [row for row in service_types if row.group == key]

		names = sorted({part.material_issue for part in members if part.material_issue})
		if pending:
			names += [
				name
				for name, issue in issues.items()
				if issue.status == APPROVAL_REJECTED and issue.group == key and name not in names
			]

		groups.append(
			frappe._dict(
				group=key,
				label=(group_names.get(key) or key) if key else NO_GROUP_LABEL,
				# งานในกลุ่ม — ให้รู้ว่าใบเบิกใบนี้รวมของงานไหนบ้าง
				jobs=[row.label for row in rows],
				parts=members,
				# ปุ่มขออนุมัติเบิกซ่อนเมื่อไม่เหลืออะไหล่ที่เบิกได้แล้ว — นับเฉพาะสินค้าคงคลัง
				# ไม่งั้นกลุ่มที่มีแต่ค่าบริการจะโชว์ปุ่มที่กดแล้ว throw "ไม่มีอะไหล่ที่ยังไม่ได้เบิก"
				pending=pending,
				# ตรงกับ _get_group_job: กลุ่มว่างใช้สิทธิ์ระดับใบ, กลุ่มที่มีชื่อต้องอยู่บนแถวในกลุ่ม
				# หรือเป็นหัวหน้างานของกลุ่มนั้น
				can_request=is_manager
				or (job_access if not key else (key in supervised_groups or any(row.mine for row in rows))),
				issues=[issues.get(name) or frappe._dict(name=name, **_issue_state("")) for name in names],
			)
		)

	return groups


def _issue_state(status, docstatus=0):
	key = "submitted" if docstatus == 1 else (status or "")
	label, theme = REQUISITION_STATES.get(key, REQUISITION_STATES[""])
	return {"status": status or "", "status_label": label, "theme": theme}


def _get_requisitions(doc, approver):
	"""ใบเบิกทุกใบ (ที่ยังไม่ถูกยกเลิก) ของใบสั่งงาน พร้อมสถานะอนุมัติ — query เดียว

	can_approve คิดแบบ batch ให้ตรงกับ can_approve_requisition: fallback roles อนุมัติได้ทุกใบ
	หัวหน้างานอนุมัติได้เฉพาะใบในกลุ่มที่ตัวเองดูแล
	"""
	rows = frappe.get_all(
		"Stock Entry",
		filters={"custom_service_order": doc.name, "docstatus": ["<", 2]},
		fields=[
			"name",
			"docstatus",
			"custom_service_type_group",
			"custom_approval_status",
			"custom_created_by_name",
			"custom_approved_by_name",
			"custom_rejection_reason",
		],
		order_by="creation asc",
	)

	issues = {}
	for row in rows:
		status = row.custom_approval_status or ""
		group = row.custom_service_type_group or ""
		pending = row.docstatus == 0 and status == APPROVAL_PENDING
		issues[row.name] = frappe._dict(
			name=row.name,
			group=group,
			requested_by_name=row.custom_created_by_name or "",
			approved_by_name=row.custom_approved_by_name or "",
			reason=row.custom_rejection_reason or "",
			can_approve=pending and (approver.is_fallback or (bool(group) and group in approver.groups)),
			**_issue_state(status, row.docstatus),
		)

	return issues


def _get_group_names(groups):
	"""ชื่อกลุ่มบริการ (group_name) ทีเดียวทั้งชุด"""
	groups = [group for group in groups if group]
	if not groups:
		return {}

	return dict(
		frappe.get_all(
			"Service Type Group",
			filters={"name": ["in", groups]},
			fields=["name", "group_name"],
			as_list=True,
		)
	)


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

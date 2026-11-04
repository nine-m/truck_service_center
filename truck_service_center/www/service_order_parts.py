# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""พอร์ทัลช่าง — หน้าใบเบิกอะไหล่ของใบสั่งงานหนึ่งใบ

route: /service-order-portal/<name>/parts (ผูกไว้ใน hooks.website_route_rules)
แยกออกจากหน้ารายละเอียดงาน เพราะบนมือถือ/แท็บเล็ตรายการอะไหล่ ใบเบิก และปุ่มอนุมัติ
ยาวจนดันปุ่มงานหลักตกจอ หน้านี้รวมทุกเรื่องของอะไหล่ไว้ที่เดียว:
- อะไหล่ในใบงาน จัดกลุ่มตามกลุ่มบริการ (หนึ่งกลุ่ม = ใบขออนุมัติเบิกหนึ่งใบ) + ปุ่มขออนุมัติเบิก
- ใบเบิกและสถานะอนุมัติ + ปุ่มอนุมัติ/ไม่อนุมัติของผู้อนุมัติ
- คืนอะไหล่ที่เบิกแล้วไม่ได้ใช้ (บางส่วนได้) จากการ์ดใบเบิก + ใบคืนและปุ่มอนุมัติ/ไม่อนุมัติคืน
- ฟอร์มคีย์อะไหล่ที่ต้องเบิกเพิ่ม (api.technician_portal.add_parts) — เพิ่มแถวอย่างเดียว แล้วกด
  "ขออนุมัติเบิก" ของกลุ่มเพื่อรวมทุกรายการที่ค้างเบิกในกลุ่มเป็นใบเดียว (flow อนุมัติเดิม)

ด่านเข้าหน้าเหมือนหน้ารายละเอียดงานทุกอย่าง (load_portal_job)
"""

import frappe
from frappe.utils import format_datetime, now_datetime

from truck_service_center.api.technician_portal import (
	MAX_PART_QTY,
	MAX_REQUEST_LINES,
	MAX_REQUEST_NOTE,
	SEARCH_MIN_CHARS,
)
from truck_service_center.truck_service_center.doctype.parts_return.parts_return import (
	get_return_availability,
)
from truck_service_center.www.service_order_job import (
	REJECT_PRESETS,
	_build_job_view,
	_get_group_names,
	_num,
	load_portal_job,
)
from truck_service_center.www.service_order_portal import NO_GROUP_LABEL

no_cache = 1

# เหตุผลคืนอะไหล่สำเร็จรูป
RETURN_PRESETS = (
	"เบิกเกิน ใช้ไม่หมด",
	"ไม่ได้ใช้ / ตรวจแล้วไม่ต้องเปลี่ยน",
	"ผิดรุ่น / ใส่ไม่ได้",
	"ลูกค้าไม่เปลี่ยน",
)

# เหตุผลขอเบิกสำเร็จรูปในกล่องยืนยัน "ขออนุมัติเบิก" — แตะแล้วแก้ต่อได้ ผู้อนุมัติเห็นในการ์ดใบเบิก
REQUEST_PRESETS = (
	"ตรวจพบเพิ่มระหว่างซ่อม",
	"ของเดิมชำรุด / ใช้ต่อไม่ได้",
	"จำนวนในแพ็คเกจไม่พอ",
	"ลูกค้าขอเปลี่ยนเพิ่ม",
)


def get_context(context):
	portal = load_portal_job(frappe.form_dict.get("name"))
	doc = portal.doc
	job_access = not portal.supervisor_view

	# บังคับให้มี csrf token ในหน้า เพื่อให้ frappe.call ยิง POST ได้
	frappe.sessions.get_csrf_token()

	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True
	context.title = f"ใบเบิกอะไหล่ {doc.name}"
	context.fetched_at = format_datetime(now_datetime(), "HH:mm")

	context.job = _build_job_view(
		doc,
		portal.is_manager,
		approver=portal.approver,
		doc_open=portal.doc_open,
		job_access=job_access,
	)
	context.doc_open = portal.doc_open
	context.is_manager = portal.is_manager
	context.reject_presets = REJECT_PRESETS
	context.request_presets = REQUEST_PRESETS
	context.return_presets = RETURN_PRESETS
	# ต้องรับรถก่อนจึงเบิกได้ — เกณฑ์เดียวกับ create_material_issue_for_rows
	context.received = bool(doc.received_date) or doc.status == "In Progress"

	user = frappe.session.user
	for group in context.job.part_groups:
		for part in group.parts:
			part.requested_by_name = ""
			part.can_remove = (
				portal.doc_open
				and bool(part.requested_by)
				and not part.material_issue
				and (part.requested_by == user or portal.is_manager)
			)
	_attach_requester_names(context.job.part_groups)
	_attach_return_lines(doc, context.job.part_groups, portal.doc_open)

	context.request_targets = build_request_targets(
		context.job.service_types,
		_get_group_names({row.group for row in context.job.service_types}),
		is_manager=portal.is_manager,
		supervised_groups=portal.approver.groups,
		job_access=job_access,
	)
	context.can_request = portal.doc_open and bool(context.request_targets)
	context.limits = frappe._dict(
		min_chars=SEARCH_MIN_CHARS,
		max_qty=MAX_PART_QTY,
		max_lines=MAX_REQUEST_LINES,
		max_note=MAX_REQUEST_NOTE,
	)
	return context


def build_request_targets(
	service_types, group_names, is_manager=False, supervised_groups=(), job_access=True
):
	"""งานที่ผู้ใช้เลือกผูกอะไหล่ที่ขอเพิ่มได้ — สิทธิ์ตรงกับ _get_group_job ของ api

	กลุ่มที่มีชื่อ: หัวหน้าช่าง, หัวหน้างานของกลุ่มนั้น หรือช่างที่อยู่บนงานแถวนั้น
	งานที่ไม่มีกลุ่ม และตัวเลือก "ไม่ระบุงาน" ใช้สิทธิ์ระดับใบ (ช่างในใบ / หัวหน้าช่าง)
	งานประเภทเดียวกัน + แพ็คเกจเดียวกันหลายแถว ได้ provenance เดียวกัน จึงแสดงตัวเลือกเดียว
	"""
	targets = []
	seen = set()
	for row in service_types:
		if not row.label:
			continue
		key = (row.label, row.package)
		if key in seen:
			continue
		if row.group:
			allowed = is_manager or row.group in supervised_groups or row.mine
		else:
			allowed = is_manager or job_access
		if not allowed:
			continue
		seen.add(key)
		targets.append(
			frappe._dict(
				row=row.name,
				label=row.label,
				package=row.package,
				group_label=group_names.get(row.group) or row.group or NO_GROUP_LABEL,
			)
		)

	if is_manager or job_access:
		targets.append(frappe._dict(row="", label="ไม่ระบุงาน", package="", group_label=NO_GROUP_LABEL))

	return targets


def _attach_return_lines(doc, part_groups, doc_open):
	"""แถวที่คืนได้ของแต่ละใบเบิก — ปุ่ม "คืนอะไหล่" ขึ้นเมื่อมีอย่างน้อยหนึ่งแถวที่คืนได้

	สิทธิ์ขอคืนเท่ากับสิทธิ์ขอเบิกกลุ่มนั้น (group.can_request ↔ _get_group_job ของ api)
	ใบที่ยังรออนุมัติ / submit แล้ว / ไม่อนุมัติ ไม่อยู่ใน availability จึงไม่มีปุ่ม
	"""
	issues = [issue for group in part_groups for issue in group.issues]
	availability = get_return_availability(doc, [issue.name for issue in issues]) if doc_open else {}

	for group in part_groups:
		for issue in group.issues:
			lines = availability.get(issue.name) or {}
			issue.return_lines = [
				frappe._dict(
					row=row_name,
					label=info.label,
					uom=info.uom,
					issued=_num(info.issued_qty),
					pending=_num(info.pending_qty),
					max_qty=_num(info.max_qty),
				)
				for row_name, info in lines.items()
				if info.max_qty > 0
			]
			issue.can_return = bool(issue.return_lines) and group.can_request


def _attach_requester_names(part_groups):
	"""ชื่อเต็มของช่างที่ขอเพิ่ม — query เดียวทั้งหน้า"""
	parts = [part for group in part_groups for part in group.parts if part.requested_by]
	if not parts:
		return

	names = dict(
		frappe.get_all(
			"User",
			filters={"name": ["in", list({part.requested_by for part in parts})]},
			fields=["name", "full_name"],
			as_list=True,
		)
	)
	for part in parts:
		part.requested_by_name = names.get(part.requested_by) or part.requested_by

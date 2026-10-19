# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""พอร์ทัลช่าง — รายการใบสั่งงานที่ยังไม่จบ

ช่างเห็นเฉพาะใบที่ตัวเองถูก assign ส่วน role ใน MANAGER_ROLES (เช่น Technician Manager)
เห็นทุกใบ หัวหน้างานกลุ่มเห็นใบที่ตัวเองถูก assign + ใบที่มีงานในกลุ่มบริการที่ตัวเองดูแล
ช่างถูกส่งมาที่หน้านี้หลัง login ผ่าน hook `role_home_page`
"""

import frappe
from frappe import _
from frappe.utils import format_datetime, now_datetime

from truck_service_center.api.technician_portal import MANAGER_ROLES, TECHNICIAN_FIELDS
from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	APPROVAL_PENDING,
	get_supervised_groups,
)
from truck_service_center.truck_service_center.doctype.service_type_group.service_type_group import (
	APPROVER_FALLBACK_ROLES,
)

no_cache = 1

# ใบงานสูงสุดที่ดึงมาแสดง — POC ยังไม่ทำ pagination
PAGE_LIMIT = 50

# แสดงเฉพาะงานที่ยังไม่จบ ช่างจะได้เห็นแต่สิ่งที่ต้องลงมือทำ
OPEN_STATUSES = ("Draft", "In Progress", "On Hold")

# หัวหน้าช่างเห็นงานที่ปิดแล้วแต่รถยังรอส่งมอบด้วย — พ้นมือช่างแต่ยังอยู่ในความดูแลของหัวหน้า
MANAGER_STATUSES = (*OPEN_STATUSES, "Ready for Delivery")

# สีสถานะให้ตรงกับ list view บน desk (service_order_list.js)
# หมายเหตุ: desk ใช้ "gray" แต่ es-badge บนเว็บรู้จักเฉพาะ "grey" (สะกดแบบอังกฤษ)
STATUS_THEMES = {
	"Draft": "red",
	"In Progress": "orange",
	"Ready for Delivery": "blue",
	"Completed": "green",
	"Cancelled": "grey",
	"On Hold": "yellow",
}

STATUS_LABELS = {
	"Draft": "ร่าง",
	"In Progress": "กำลังดำเนินการ",
	"Ready for Delivery": "รอส่งมอบรถ",
	"Completed": "เสร็จสิ้น",
	"Cancelled": "ยกเลิก",
	"On Hold": "พักงาน",
}

# ป้ายกลุ่มของอะไหล่ที่ไม่มีกลุ่มบริการ — ใบเบิกกลุ่มนี้หัวหน้าช่าง/ผู้จัดการเป็นผู้อนุมัติ
NO_GROUP_LABEL = "อะไหล่อื่น ๆ / ไม่มีกลุ่ม"

PRIORITY_LABELS = {
	"Low": "ต่ำ",
	"Medium": "ปานกลาง",
	"High": "สูง",
	"Urgent": "ด่วนมาก",
}


def get_context(context):
	if frappe.session.user == "Guest":
		# frappe จะแปลงเป็นหน้า "Not Permitted" พร้อมปุ่ม Login
		# ที่ชี้ไป /login?redirect-to=/service-order-portal ให้เอง
		frappe.throw(_("You need to be logged in to access this page"), frappe.PermissionError)

	user = frappe.session.user

	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True
	context.title = "งานของฉัน"
	context.fetched_at = format_datetime(now_datetime(), "HH:mm")
	context.technician_name = frappe.db.get_value("User", user, "full_name") or user
	# ไม่ได้กันคนที่ไม่ใช่ช่างออกจากหน้านี้ (ผู้จัดการ/แอดมินเปิดดูได้เพื่อตรวจสอบ)
	# ใช้แค่บอกสาเหตุตอนรายการว่าง
	roles = set(frappe.get_roles(user))
	context.is_technician = "Technician" in roles
	# หัวหน้าช่าง/ผู้จัดการเห็นงานที่ยังไม่จบทุกใบ ไม่ใช่เฉพาะใบที่ถูก assign
	context.sees_all = bool(MANAGER_ROLES & roles)
	supervised_groups = get_supervised_groups(user)
	# หัวหน้างานกลุ่มต้องเห็นว่าใบไหนมีช่างคนไหนแล้ว เพื่อ assign งานในกลุ่มของตน
	context.is_supervisor = bool(supervised_groups) and not context.sees_all
	context.orders = get_open_orders(user, all_jobs=context.sees_all, groups=supervised_groups)
	context.order_count = len(context.orders)

	# ใบเบิกที่รอให้ผู้ใช้คนนี้อนุมัติ — หัวหน้างานกลุ่มเห็นเฉพาะกลุ่มของตน หัวหน้าช่าง/ผู้จัดการเห็นทุกใบ
	context.pending_requisitions = get_pending_requisitions(
		is_fallback=bool(APPROVER_FALLBACK_ROLES & roles), groups=supervised_groups
	)

	return context


def get_pending_requisitions(is_fallback=False, groups=(), limit=PAGE_LIMIT):
	"""ใบเบิกอะไหล่ (Stock Entry Draft) ที่รออนุมัติ พร้อมรายการอะไหล่ — 4 query ไม่ว่าจะกี่ใบ

	ใช้ frappe.get_all โดยเจตนา: หัวหน้างานกลุ่มไม่มีสิทธิ์ Stock Entry เลย ขอบเขตคือ filter
	กลุ่มที่ผูกกับ session user ด้านล่าง (ด่านอนุมัติจริงอยู่ที่ approve_requisition)
	"""
	if not is_fallback and not groups:
		return []

	filters = {
		"docstatus": 0,
		"custom_approval_status": APPROVAL_PENDING,
		"custom_service_order": ["is", "set"],
	}
	if not is_fallback:
		filters["custom_service_type_group"] = ["in", list(groups)]

	rows = frappe.get_all(
		"Stock Entry",
		filters=filters,
		fields=[
			"name",
			"custom_service_order",
			"custom_service_type_group",
			"custom_created_by_name",
			"creation",
		],
		order_by="creation asc",
		limit_page_length=limit,
	)
	if not rows:
		return []

	lines = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ["in", [row.name for row in rows]]},
		fields=["parent", "item_code", "item_name", "qty", "uom"],
		order_by="idx asc",
	)
	group_names = dict(
		frappe.get_all(
			"Service Type Group",
			filters={"name": ["in", list({row.custom_service_type_group for row in rows} - {None})]},
			fields=["name", "group_name"],
			as_list=True,
		)
	)
	orders = {
		order.name: order
		for order in frappe.get_all(
			"Service Order",
			filters={"name": ["in", list({row.custom_service_order for row in rows})]},
			fields=["name", "truck_number", "vehicle"],
		)
	}

	lines_by_entry = {}
	for line in lines:
		lines_by_entry.setdefault(line.parent, []).append(
			frappe._dict(label=line.item_name or line.item_code, qty=_qty(line.qty), uom=line.uom or "")
		)

	for row in rows:
		order = orders.get(row.custom_service_order) or frappe._dict()
		row.service_order = row.custom_service_order
		row.truck_label = order.truck_number or order.vehicle or "-"
		row.group_label = (
			group_names.get(row.custom_service_type_group) or row.custom_service_type_group
			if row.custom_service_type_group
			else NO_GROUP_LABEL
		)
		row.requested_by_name = row.custom_created_by_name or "-"
		row.requested_at = format_datetime(row.creation, "dd/MM HH:mm")
		row.lines = lines_by_entry.get(row.name, [])

	return rows


def _qty(value):
	"""ตัด .0 ท้ายจำนวนเต็ม — 2.0 ชิ้นอ่านแปลก"""
	number = float(value or 0)
	return int(number) if number == int(number) else number


def get_open_orders(user, all_jobs=False, groups=(), limit=PAGE_LIMIT):
	"""ใบสั่งงานที่ยังไม่จบ ปกติเฉพาะใบที่ `user` เป็นช่างผู้รับผิดชอบ (ช่องใดช่องหนึ่งใน 10 ช่อง)

	all_jobs=True สำหรับหัวหน้าช่าง/ผู้จัดการ — คืนทุกใบที่ยังไม่จบ รวมงานรอส่งมอบรถ
	groups = กลุ่มบริการที่ user เป็นหัวหน้างาน — เพิ่มใบที่มีแถวงานในกลุ่มนั้นเข้ามาด้วย
	(สถานะชุดเดียวกับหัวหน้าช่าง) ใช้ query เพิ่มหนึ่งครั้งหา parent จาก child table

	ใช้ frappe.get_all (ignore_permissions=True) โดยเจตนา — ขอบเขตความปลอดภัยคือ
	or_filters ที่ผูกกับ frappe.session.user ซึ่ง request แก้ไขไม่ได้
	ถ้าวันหนึ่งเพิ่ม permission_query_conditions ให้ Service Order แล้ว
	ให้เปลี่ยนมาใช้ frappe.get_list และลบ or_filters ชุดนี้ทิ้ง
	"""
	or_filters = None
	statuses = MANAGER_STATUSES if all_jobs else OPEN_STATUSES
	if not all_jobs:
		or_filters = {fieldname: user for fieldname in TECHNICIAN_FIELDS}
		group_orders = _get_orders_in_groups(groups)
		if group_orders:
			or_filters["name"] = ["in", group_orders]
			statuses = MANAGER_STATUSES

	rows = frappe.get_all(
		"Service Order",
		fields=[
			"name",
			"status",
			"service_date",
			"customer",
			"vehicle",
			"truck_number",
			"priority",
			*TECHNICIAN_FIELDS,
		],
		filters={"status": ["in", statuses], "docstatus": ["<", 2]},
		# or_filters ถูกประกอบเป็นวงเล็บก้อนเดียว (grouped_or_conditions ใน db_query.py)
		# จึงได้ ... AND (technician=u OR technician_2=u OR ... OR name in (...))
		or_filters=or_filters,
		# งานที่ค้างนานที่สุดอยู่บนสุด — เรียงแบบคิวงาน
		order_by="service_date asc, modified asc",
		limit_page_length=limit,
	)

	_attach_packages(rows)
	_attach_technician_names(rows)

	return [_decorate(row) for row in rows]


def _get_orders_in_groups(groups):
	"""ใบสั่งงานที่ยังเป็น draft และมีแถวงานในกลุ่มบริการที่ระบุ — query เดียว"""
	if not groups:
		return []

	return list(
		set(
			frappe.get_all(
				"Service Order Service Type",
				filters={
					"parenttype": "Service Order",
					"service_type_group": ["in", list(groups)],
					"docstatus": 0,
				},
				pluck="parent",
			)
		)
	)


def _attach_technician_names(rows):
	"""เติมชื่อช่างของแต่ละใบ แปลง user id เป็นชื่อจริงด้วย query เดียว

	ใช้ตอนหัวหน้าช่างเห็นทุกใบ จะได้รู้ว่าใบไหนเป็นของช่างคนไหน
	"""
	for row in rows:
		row.technician_names = [row.get(f) for f in TECHNICIAN_FIELDS if row.get(f)]
		row.technician_labels = row.technician_names

	users = {name for row in rows for name in row.technician_names}
	if not users:
		return

	full_names = dict(
		frappe.get_all(
			"User", filters={"name": ["in", list(users)]}, fields=["name", "full_name"], as_list=True
		)
	)
	for row in rows:
		row.technician_labels = [full_names.get(name) or name for name in row.technician_names]


def _attach_packages(rows):
	"""เติมชื่อแพ็คเกจบริการให้ทุกใบด้วย query เดียว (child table ของ Service Order)"""
	if not rows:
		return

	packages = frappe.get_all(
		"Service Order Package",
		filters={"parent": ["in", [row.name for row in rows]]},
		fields=["parent", "package_name", "package_code"],
		order_by="idx asc",
	)

	by_order = {}
	for package in packages:
		label = package.package_name or package.package_code
		if label:
			by_order.setdefault(package.parent, []).append(label)

	for row in rows:
		row.packages = by_order.get(row.name, [])


def _decorate(row):
	"""เติมค่าที่ format แล้ว เพื่อให้ template ไม่ต้องคิดอะไรเลย"""
	row.status_label = STATUS_LABELS.get(row.status) or row.status or "-"
	row.status_theme = STATUS_THEMES.get(row.status, "grey")
	row.priority_label = PRIORITY_LABELS.get(row.priority) or row.priority
	row.service_date_label = (
		format_datetime(row.service_date, "dd/MM/yyyy HH:mm") if row.service_date else "-"
	)
	# truck_number เป็น fetch_from ที่ยังว่างในข้อมูลเดิมส่วนใหญ่ → ใช้ชื่อรถ (= ทะเบียน) แทน
	row.truck_label = row.truck_number or row.vehicle or "-"
	# เมื่อหัวหน้าช่างเห็นทุกใบ ต้องรู้ด้วยว่าใบไหนของช่างคนไหน
	return row

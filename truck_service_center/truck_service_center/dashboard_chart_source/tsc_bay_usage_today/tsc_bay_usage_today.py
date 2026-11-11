# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""การใช้ช่องจอดวันนี้ — กราฟแท่งซ้อนบน dashboard ของ workspace

หนึ่งแท่งต่อช่องจอด ความสูงทั้งแท่ง = ชั่วโมงรับงานของวันนี้ (ถ้าจองเกินแท่งจะสูงกว่าความจุ)
ซ้อนสามชั้นจากล่างขึ้นบน:
- **ใบสั่งงาน** — ชั่วโมงประมาณการ (estimated_time) ของแถวงานในใบสั่งงานที่ถือช่องนั้น
  นับแถวที่ยังไม่จบ และแถวที่จบวันนี้ (คือชั่วโมงที่ใช้ไปวันนี้) ไม่นับแถวที่จบไปก่อนวันนี้
  แถวที่ช่องจอดว่างใช้ช่องหลักของใบงาน แบบเดียวกับ apply_default_bay
- **นัดหมาย (ยังไม่เปิดใบงาน)** — allocated_hours ของนัดวันนี้ที่ยังไม่มี service_order
  นัดที่เปิดใบงานแล้วไม่นับซ้ำ เพราะชั่วโมงของมันย้ายไปอยู่ในชั้นใบสั่งงานแล้ว
- **ว่าง** — ความจุที่เหลือ (ไม่ติดลบ)

ความจุมาจาก get_bay_availability ตัวเดียวกับฟอร์ม/ปฏิทิน/Bay Monitor จึงตรงกันโดยโครงสร้าง
ตัวกรองนัดหมายใช้ _get_appointments ของ Bay Monitor (ฉบับร่างนับ ไม่นับ Cancelled/No Show)

ไม่ใส่ @cache_source โดยเจตนา — เป็นตัวเลขของวันนี้ที่ขยับทั้งวัน cache ไว้จะเห็นเลขเก่า
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate, today

from truck_service_center.branches import get_allowed_branches, get_default_branch, is_branch_allowed
from truck_service_center.truck_service_center.doctype.service_appointment.service_appointment import (
	get_bay_availability,
)
from truck_service_center.truck_service_center.doctype.service_order.service_order import OPEN_STATUSES
from truck_service_center.www.bay_monitor import _get_appointments

LABEL_ORDER = "ใบสั่งงาน (SO)"
LABEL_SCHEDULED = "นัดหมาย (ยังไม่เปิด SO)"
LABEL_FREE = "ว่าง"
CLOSED_SUFFIX = " (ปิด)"


@frappe.whitelist()
def get(
	chart_name=None,
	chart=None,
	no_cache=None,
	filters=None,
	from_date=None,
	to_date=None,
	timespan=None,
	time_interval=None,
	heatmap_year=None,
	refresh=None,
):
	# เปิดให้ผู้ใช้ desk ทุก role เหมือน Bay Monitor — ไม่มีตัวเลขเงินหรือข้อมูลลูกค้า
	if frappe.session.user == "Guest" or (
		frappe.session.user != "Administrator"
		and frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User"
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	filters = frappe.parse_json(filters) or {}
	branch = resolve_branch(filters.get("branch"))
	date = getdate(today())

	availability = get_bay_availability(date, branch=branch)
	appointments, appointment_bays = _get_appointments(date, branch)
	order_rows = get_order_rows(date, branch)

	return build_chart(
		availability["bays"],
		hours_from_orders(order_rows, date),
		hours_from_appointments(appointments, appointment_bays),
	)


def resolve_branch(requested):
	"""สาขาที่ขอ (ต้องมีสิทธิ์) หรือว่าง = ทุกสาขาที่เห็นได้ — ค่าที่ไม่มีสิทธิ์ถอยไปสาขาเริ่มต้น

	ไม่ throw เมื่อไม่มีสิทธิ์ เพราะตัวกรองของกราฟถูกเก็บไว้ใน user settings ข้ามการเปลี่ยนสิทธิ์
	ถ้า throw กราฟจะพังถาวรจนกว่าผู้ใช้จะรู้ว่าต้องไปล้างตัวกรองเอง
	"""
	if requested and is_branch_allowed(requested):
		return requested
	if requested:
		return get_default_branch()
	return None


# ── pure functions ───────────────────────────────────────────────────────────


def hours_from_orders(rows, date):
	"""{ช่องจอด: ชั่วโมง} จากแถวงานของใบสั่งงาน

	rows: dict ที่มี main_bay, service_bay, estimated_time, end_time
	แถวที่จบก่อนวันนี้ไม่นับ (งานนั้นใช้ช่องไปแล้วในวันก่อน) แถวที่ไม่มีช่องจอดเลยไม่มีแท่งให้ลง
	"""
	date = getdate(date)
	hours = {}
	for row in rows or []:
		end = row.get("end_time")
		if end and getdate(get_datetime(end)) < date:
			continue
		bay = row.get("service_bay") or row.get("main_bay")
		if not bay:
			continue
		hours[bay] = hours.get(bay, 0) + flt(row.get("estimated_time"))
	return hours


def hours_from_appointments(appointments, bay_rows):
	"""{ช่องจอด: ชั่วโมง} จากนัดหมายที่ยังไม่เปิดใบสั่งงาน"""
	pending = {appt.get("name") for appt in appointments or [] if not appt.get("service_order")}
	hours = {}
	for row in bay_rows or []:
		bay = row.get("service_bay")
		if not bay or row.get("parent") not in pending:
			continue
		hours[bay] = hours.get(bay, 0) + flt(row.get("allocated_hours"))
	return hours


def build_chart(cap_rows, order_hours, scheduled_hours):
	"""ข้อมูลของ frappe-charts แบบแท่งซ้อน — ลำดับ datasets คือลำดับซ้อนจากล่างขึ้นบน

	ช่องจอดที่ปิดใบงาน/นัดยังโผล่ได้ (รถจอดค้างวันปิด) จึงเก็บแท่งไว้ แค่ต่อท้ายชื่อว่า (ปิด)
	ช่องจอดที่ถูกปิดใช้งานไม่อยู่ใน cap_rows จึงไม่มีแท่ง — Bay Monitor แสดงกรณีนี้แยกไว้แล้ว
	"""
	labels, orders, scheduled, free = [], [], [], []
	for row in cap_rows or []:
		bay = row["bay"]
		cap = max(flt(row.get("cap")), 0)
		used_order = flt(order_hours.get(bay), 1)
		used_scheduled = flt(scheduled_hours.get(bay), 1)

		label = row.get("bay_name") or bay
		if row.get("is_closed"):
			label += CLOSED_SUFFIX
		labels.append(label)
		orders.append(used_order)
		scheduled.append(used_scheduled)
		free.append(flt(max(cap - used_order - used_scheduled, 0), 1))

	return {
		"labels": labels,
		"datasets": [
			{"name": LABEL_ORDER, "values": orders},
			{"name": LABEL_SCHEDULED, "values": scheduled},
			{"name": LABEL_FREE, "values": free},
		],
	}


# ── IO ───────────────────────────────────────────────────────────────────────


def get_order_rows(date, branch=None):
	"""แถวงานที่ใช้ช่องจอดวันนี้ — query เดียว

	ใบงานที่ยังเปิด (สถานะชุดเดียวกับ get_busy_bays) ทุกแถวที่ยังไม่จบ/จบวันนี้
	รวมใบงานที่ปิด/submit ไปแล้วแต่มีแถวจบวันนี้ ไม่งั้นงานที่เสร็จบ่ายนี้จะหายจากกราฟทั้งที่ใช้ช่องไปแล้ว
	"""
	so = frappe.qb.DocType("Service Order")
	row = frappe.qb.DocType("Service Order Service Type")
	day_start = get_datetime(f"{getdate(date)} 00:00:00")

	is_open = (so.docstatus == 0) & so.status.isin(list(OPEN_STATUSES))
	ended_today = row.end_time >= day_start

	query = (
		frappe.qb.from_(so)
		.join(row)
		.on((row.parent == so.name) & (row.parenttype == "Service Order"))
		.select(
			so.service_bay.as_("main_bay"),
			row.service_bay,
			row.estimated_time,
			row.end_time,
		)
		.where(so.docstatus < 2)
		.where(is_open | ended_today)
		.where(row.end_time.isnull() | ended_today)
	)

	if branch:
		query = query.where(so.branch == branch)
	else:
		allowed = get_allowed_branches()
		if allowed is not None:
			query = query.where(so.branch.isin(allowed))

	return query.run(as_dict=True)

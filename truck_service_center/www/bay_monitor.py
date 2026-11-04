# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""Bay Monitor — dashboard สถานะช่องจอดซ่อม (/bay-monitor)

แสดงสองเรื่องคู่กันต่อช่องจอด เพราะสองเรื่องนี้ไม่จำเป็นต้องตรงกัน:
- **ใช้งานจริง** — ใบสั่งงานที่ยังเปิดอยู่ซึ่งถือช่องจอดนั้น (ช่องหลัก หรือช่องรายแถวที่งานยังไม่จบ)
  เป็นสถานะ ณ ตอนนี้ จึงแสดงเฉพาะเมื่อดูวันนี้
- **การจอง** — ชั่วโมงที่นัดหมายของวันที่เลือกจองไว้ในช่องนั้น (Service Appointment Bay)
  ตัวเลขความจุมาจาก get_bay_availability ตัวเดียวกับฟอร์ม/ปฏิทินนัดหมาย จึงตรงกันโดยโครงสร้าง

เปิดให้ผู้ใช้ desk ทุก role ดูได้ (บาง role เช่น Stock User ไม่มีสิทธิ์อ่าน Service Appointment)
จึงใช้ frappe.get_all โดยเจตนา และดึงเฉพาะฟิลด์ที่ต้องแสดง — ไม่มีตัวเลขเงิน
Website User (ลูกค้า) เข้าไม่ได้ เพราะหน้านี้เห็นรถของลูกค้าทุกราย

ตรรกะจัดกลุ่ม/ตัดสินสถานะเป็น pure function ระดับ module เพื่อให้เทสต์ได้โดยไม่ต้อง insert เอกสาร
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, format_datetime, get_datetime, getdate, now_datetime, today

from truck_service_center.api.technician_portal import TECHNICIAN_FIELDS
from truck_service_center.truck_service_center.doctype.service_appointment.service_appointment import (
	EXCLUDED_STATUSES,
	STATUS_CLOSED,
	STATUS_FREE,
	STATUS_FULL,
	STATUS_NEAR_FULL,
	get_bay_availability,
)
from truck_service_center.truck_service_center.doctype.service_order.service_order import OPEN_STATUSES
from truck_service_center.www.service_order_portal import STATUS_LABELS, STATUS_THEMES

no_cache = 1

# หน้าจอทีวีหน้าศูนย์เปิดค้างไว้ทั้งวัน — โหลดใหม่ทุก 60 วินาที
REFRESH_SECONDS = 60

# สถานะของช่องจอดบนการ์ด เรียงจากสำคัญมากไปน้อย
STATE_CLOSED = "closed"
STATE_IN_USE = "in_use"
STATE_WAITING = "waiting"
STATE_BOOKED = "booked"
STATE_FREE = "free"

STATE_LABELS = {
	STATE_CLOSED: "ปิดทำการ",
	STATE_IN_USE: "ใช้งานอยู่",
	STATE_WAITING: "รอรถเข้า",
	STATE_BOOKED: "มีจอง",
	STATE_FREE: "ว่าง",
}

# es-badge บนเว็บรู้จัก "grey" ไม่ใช่ "gray" (ดู service_order_portal.STATUS_THEMES)
STATE_THEMES = {
	STATE_CLOSED: "grey",
	STATE_IN_USE: "orange",
	STATE_WAITING: "yellow",
	STATE_BOOKED: "blue",
	STATE_FREE: "green",
}

CAPACITY_THEMES = {
	STATUS_CLOSED: "grey",
	STATUS_FULL: "red",
	STATUS_NEAR_FULL: "orange",
	STATUS_FREE: "green",
}

APPOINTMENT_STATUS_LABELS = {
	"Scheduled": "นัดแล้ว",
	"Confirmed": "ยืนยันแล้ว",
	"In Progress": "รับรถแล้ว",
	"Completed": "เสร็จสิ้น",
}

# สถานะการมาถึงของนัดหมาย — ดูจาก service_order ที่ผูกไว้ ไม่ใช่ status ของนัด
# (นัดเก่าบางใบสร้างใบสั่งงานแล้วแต่ status ไม่ถูกขยับ)
ARRIVAL_ARRIVED = "arrived"
ARRIVAL_LATE = "late"
ARRIVAL_PENDING = "pending"

ARRIVAL_LABELS = {
	ARRIVAL_ARRIVED: "มาถึงแล้ว",
	ARRIVAL_LATE: "เลยเวลานัด",
	ARRIVAL_PENDING: "ยังไม่มา",
}

ARRIVAL_THEMES = {
	ARRIVAL_ARRIVED: "green",
	ARRIVAL_LATE: "red",
	ARRIVAL_PENDING: "grey",
}

# ชื่อวันภาษาไทย ตาม date.weekday() — babel จะใช้ภาษาของผู้ใช้ซึ่งส่วนใหญ่ยังเป็นอังกฤษ
THAI_WEEKDAYS = ("จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์")

# ป้ายกลุ่มของช่องจอดที่ไม่มีประเภท
NO_BAY_TYPE_LABEL = "ไม่ระบุประเภท"


def get_context(context):
	if frappe.session.user == "Guest":
		# frappe แปลงเป็นหน้า Not Permitted พร้อมปุ่ม Login ที่มี ?redirect-to= ให้เอง
		frappe.throw(_("You need to be logged in to access this page"), frappe.PermissionError)

	if frappe.session.user != "Administrator" and (
		frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User"
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	selected = _parse_date(frappe.form_dict.get("date"))
	now = now_datetime()
	is_today = selected == getdate(now)

	context.no_cache = 1
	context.full_width = True
	context.show_sidebar = False
	context.no_breadcrumbs = True
	context.title = "Bay Monitor"
	context.refresh_seconds = REFRESH_SECONDS
	context.fetched_at = format_datetime(now, "HH:mm")
	context.selected_date = str(selected)
	context.date_label = f"วัน{THAI_WEEKDAYS[selected.weekday()]}ที่ {selected.strftime('%d/%m/%Y')}"
	context.prev_date = str(add_days(selected, -1))
	context.next_date = str(add_days(selected, 1))
	context.is_today = is_today
	context.today = today()

	context.board = get_board(selected, now, is_today)
	return context


def _parse_date(value):
	"""?date=YYYY-MM-DD — ค่าเพี้ยนให้ถอยไปวันนี้ ไม่ต้อง error ทั้งหน้า"""
	if not value:
		return getdate(today())
	try:
		return getdate(value)
	except Exception:
		return getdate(today())


def get_board(date, now, is_today):
	"""ประกอบข้อมูลทั้งหน้า — จำนวน query คงที่ ไม่ขึ้นกับจำนวนช่องจอด/รถ"""
	availability = get_bay_availability(date)
	appointments, appointment_bays = _get_appointments(date)
	bookings, unallocated = collect_bookings(appointments, appointment_bays, now, is_today)

	occupants, unassigned = {}, []
	if is_today:
		orders, service_rows = _get_open_orders()
		_attach_appointments(orders)
		_attach_technician_labels(orders)
		occupants, unassigned = collect_occupants(orders, service_rows, now)

	bays = [
		build_bay_card(row, occupants.get(row["bay"], []), bookings.get(row["bay"], []), is_today)
		for row in availability["bays"]
	]

	# ใบงานที่ถือช่องจอดซึ่งถูกปิดใช้งานไปแล้ว — ไม่มีการ์ดให้แสดง จึงย้ายไปกลุ่มยังไม่จัดช่อง
	active_bays = {row["bay"] for row in availability["bays"]}
	for bay, items in occupants.items():
		if bay not in active_bays:
			listed = {item.name for item in unassigned}
			unassigned.extend(item for item in items if item.name not in listed)

	summary = availability["summary"]
	in_shop = [] if not is_today else _unique_orders(occupants, unassigned)

	return frappe._dict(
		groups=group_by_bay_type(bays),
		summary=frappe._dict(
			bay_count=len(bays),
			in_use=sum(1 for bay in bays if bay.state == STATE_IN_USE),
			free_now=sum(1 for bay in bays if bay.state in (STATE_FREE, STATE_BOOKED)),
			closed=sum(1 for bay in bays if bay.state == STATE_CLOSED),
			vehicles_in_shop=sum(1 for item in in_shop if item.in_bay),
			waiting_receive=sum(1 for item in in_shop if not item.in_bay),
			booked=_hours(summary["booked"]),
			cap=_hours(summary["cap"]),
			free=_hours(summary["free"]),
			over=_hours(summary["over"]),
			capacity_status=summary["status"],
			capacity_theme=CAPACITY_THEMES.get(summary["status"], "grey"),
			capacity_percent=_percent(summary["booked"], summary["cap"]),
			day_note=summary["day_note"],
			by_type=[
				frappe._dict(
					label=item["bay_type_name"] or NO_BAY_TYPE_LABEL,
					booked=_hours(item["booked"]),
					cap=_hours(item["cap"]),
					status=item["status"],
					theme=CAPACITY_THEMES.get(item["status"], "grey"),
				)
				for item in summary["by_type"]
			],
			appointment_count=len(appointments),
			arrived=sum(1 for appt in appointments if appt.arrival == ARRIVAL_ARRIVED),
			late=sum(1 for appt in appointments if appt.arrival == ARRIVAL_LATE),
			pending=sum(1 for appt in appointments if appt.arrival == ARRIVAL_PENDING),
		),
		unassigned=unassigned,
		unallocated=unallocated,
	)


# ── pure functions ───────────────────────────────────────────────────────────


def appointment_arrival(appointment, now, is_today):
	"""มาถึงแล้ว / เลยเวลานัด / ยังไม่มา

	"เลยเวลา" ใช้เฉพาะวันนี้ — วันที่ผ่านมาแล้วรถไม่มาก็คือไม่มา ส่วนวันข้างหน้ายังไม่ถึงเวลา
	"""
	if appointment.get("service_order") or appointment.get("status") in ("In Progress", "Completed"):
		return ARRIVAL_ARRIVED

	time = appointment.get("appointment_time")
	if is_today and time not in (None, ""):
		scheduled = get_datetime(f"{getdate(now)} {_time_label(time)}")
		if scheduled < get_datetime(now):
			return ARRIVAL_LATE

	return ARRIVAL_PENDING


def collect_bookings(appointments, bay_rows, now, is_today):
	"""แยกการจองตามช่องจอด → ({ช่องจอด: [การจอง]}, [นัดที่ยังไม่ได้จัดช่องจอด])

	นัดหนึ่งใบจองได้หลายช่อง (แยกตามประเภทช่องจอด) จึงขึ้นในทุกช่องที่จองพร้อมชั่วโมงของช่องนั้น
	เติม arrival / label ลงใน appointment เดิมด้วย ให้ผู้เรียกนับสรุปจากรายการเดียวกันได้
	"""
	for appointment in appointments:
		appointment.arrival = appointment_arrival(appointment, now, is_today)
		appointment.arrival_label = ARRIVAL_LABELS[appointment.arrival]
		appointment.arrival_theme = ARRIVAL_THEMES[appointment.arrival]
		appointment.truck_label = (
			appointment.get("license_plate")
			or appointment.get("truck_number")
			or appointment.get("vehicle")
			or "-"
		)
		appointment.time_label = _time_label(appointment.get("appointment_time"))
		appointment.status_label = APPOINTMENT_STATUS_LABELS.get(
			appointment.get("status")
		) or appointment.get("status")
		appointment.hours_label = _hours(appointment.get("estimated_duration"))

	by_name = {appointment.name: appointment for appointment in appointments}

	bookings = {}
	allocated = set()
	for row in bay_rows:
		appointment = by_name.get(row.get("parent"))
		if not appointment or not row.get("service_bay"):
			continue
		allocated.add(appointment.name)
		bookings.setdefault(row["service_bay"], []).append(
			frappe._dict(appointment, allocated_hours=_hours(row.get("allocated_hours")))
		)

	for items in bookings.values():
		items.sort(key=_booking_sort_key)

	unallocated = sorted(
		(appointment for appointment in appointments if appointment.name not in allocated),
		key=_booking_sort_key,
	)
	return bookings, unallocated


def collect_occupants(orders, service_rows, now):
	"""ใบสั่งงานที่เปิดอยู่ แยกตามช่องจอดที่ถือ → ({ช่องจอด: [ใบงาน]}, [ใบงานที่ไม่มีช่องจอด])

	ใบงานถือช่องหลักตลอดที่ยังเปิด และถือช่องรายแถวเฉพาะแถวที่งานยังไม่จบ
	(แถวที่ช่องจอดว่างใช้ช่องหลัก — apply_default_bay เติมให้ตอนบันทึกอยู่แล้ว)
	ต่างจาก get_busy_bays ของใบสั่งงานตรงที่ปล่อยช่องของแถวที่จบแล้ว เพราะหน้านี้ตอบว่า
	"ตอนนี้มีรถอยู่ในช่องไหม" ไม่ใช่ "ช่องนี้ยังผูกกับใบงานไหม"
	"""
	rows_by_order = {}
	for row in service_rows:
		rows_by_order.setdefault(row.get("parent"), []).append(row)

	occupants = {}
	unassigned = []
	for order in orders:
		rows = rows_by_order.get(order.name, [])
		bays = {}
		if order.get("service_bay"):
			bays[order.service_bay] = []
		for row in rows:
			bay = row.get("service_bay") or order.get("service_bay")
			if not bay:
				continue
			if row.get("end_time") and bay != order.get("service_bay"):
				continue
			bays.setdefault(bay, []).append(row)

		decorated = _decorate_order(order, now)
		if not bays:
			unassigned.append(decorated)
			continue

		for bay, bay_rows in bays.items():
			occupants.setdefault(bay, []).append(
				frappe._dict(
					decorated,
					active_services=[
						row.get("service_type")
						for row in bay_rows
						if row.get("start_time") and not row.get("end_time")
					],
					done_count=sum(1 for row in bay_rows if row.get("end_time")),
					service_count=len(bay_rows),
				)
			)

	return occupants, unassigned


def bay_state(cap_row, occupants, bookings, is_today):
	"""สถานะเดียวที่โชว์บนหัวการ์ด

	รถอยู่ในช่องจริงชนะทุกอย่าง แม้วันนั้นปิดทำการ (ปิดแต่ยังมีรถจอดค้างคือสิ่งที่ต้องเห็น)
	ใบงานที่ยังไม่รับรถถือช่องไว้ = รอรถเข้า
	"""
	if is_today:
		if any(item.in_bay for item in occupants):
			return STATE_IN_USE
		if occupants:
			return STATE_WAITING
	if cap_row.get("is_closed"):
		return STATE_CLOSED
	if bookings:
		return STATE_BOOKED
	return STATE_FREE


def build_bay_card(cap_row, occupants, bookings, is_today):
	state = bay_state(cap_row, occupants, bookings, is_today)

	# รถในช่องที่ไม่มีนัดผูกไว้เลย = walk-in — เทียบกับนัดของวันนี้ในช่องนี้เพื่อบอกว่าการจอง
	# ใบไหนเป็นรถคันที่อยู่ในช่องแล้ว
	occupant_orders = {item.name for item in occupants}
	for booking in bookings:
		booking.in_this_bay = bool(booking.get("service_order")) and booking.service_order in occupant_orders

	return frappe._dict(
		bay=cap_row["bay"],
		bay_name=cap_row.get("bay_name") or cap_row["bay"],
		bay_type=cap_row.get("bay_type"),
		bay_type_name=cap_row.get("bay_type_name") or NO_BAY_TYPE_LABEL,
		state=state,
		state_label=STATE_LABELS[state],
		state_theme=STATE_THEMES[state],
		cap=_hours(cap_row.get("cap")),
		booked=_hours(cap_row.get("booked")),
		free=_hours(max(cap_row.get("cap") or 0, 0) - (cap_row.get("booked") or 0)),
		is_over=(cap_row.get("booked") or 0) > (cap_row.get("cap") or 0),
		capacity_percent=_percent(cap_row.get("booked"), cap_row.get("cap")),
		capacity_status=cap_row.get("status"),
		capacity_theme=CAPACITY_THEMES.get(cap_row.get("status"), "grey"),
		closed_reason=cap_row.get("reason") if cap_row.get("is_closed") else None,
		occupants=occupants,
		bookings=bookings,
	)


def group_by_bay_type(cards):
	"""จัดการ์ดเป็นกลุ่มตามประเภทช่องจอด เรียงตามชื่อประเภท (ในกลุ่มคงลำดับชื่อช่องจอดเดิม)"""
	groups = {}
	for card in cards:
		groups.setdefault(card.bay_type_name, []).append(card)

	return [frappe._dict(label=label, bays=groups[label]) for label in sorted(groups)]


# ── IO ───────────────────────────────────────────────────────────────────────


def _get_appointments(date):
	"""นัดหมายของวัน + แถวช่องจอดที่จองไว้ — ตัวกรองชุดเดียวกับ get_booked_hours_range
	(ฉบับร่างนับด้วย ไม่นับ Cancelled/No Show) ตัวเลขบนการ์ดจึงตรงกับรายการจองที่แสดง
	"""
	appointments = frappe.get_all(
		"Service Appointment",
		filters={
			"appointment_date": date,
			"docstatus": ["!=", 2],
			"status": ["not in", list(EXCLUDED_STATUSES)],
		},
		fields=[
			"name",
			"appointment_time",
			"status",
			"docstatus",
			"customer",
			"vehicle",
			"license_plate",
			"truck_number",
			"estimated_duration",
			"service_order",
		],
		order_by="appointment_time asc, name asc",
	)
	if not appointments:
		return [], []

	bay_rows = frappe.get_all(
		"Service Appointment Bay",
		filters={
			"parenttype": "Service Appointment",
			"parent": ["in", [row.name for row in appointments]],
		},
		fields=["parent", "service_bay", "allocated_hours"],
		order_by="idx asc",
	)
	return appointments, bay_rows


def _get_open_orders():
	"""ใบสั่งงานที่ยังเปิดอยู่ทุกใบ + แถวงานของใบเหล่านั้น — 2 query

	สถานะชุดเดียวกับ get_busy_bays (รวมรอส่งมอบรถ — รถยังจอดอยู่ในศูนย์)
	"""
	orders = frappe.get_all(
		"Service Order",
		filters={"docstatus": 0, "status": ["in", OPEN_STATUSES]},
		fields=[
			"name",
			"status",
			"customer",
			"vehicle",
			"truck_number",
			"service_bay",
			"service_date",
			"received_date",
			"priority",
			*TECHNICIAN_FIELDS,
		],
		order_by="service_date asc, name asc",
	)
	if not orders:
		return [], []

	service_rows = frappe.get_all(
		"Service Order Service Type",
		filters={"parenttype": "Service Order", "parent": ["in", [order.name for order in orders]]},
		fields=["parent", "service_type", "service_bay", "start_time", "end_time"],
		order_by="idx asc",
	)
	return orders, service_rows


def _attach_appointments(orders):
	"""ใบนัดที่สร้างใบงานนี้ (นัดวันไหนก็ได้) — query เดียว ไม่มีนัด = walk-in"""
	if not orders:
		return

	links = dict(
		frappe.get_all(
			"Service Appointment",
			filters={"service_order": ["in", [order.name for order in orders]], "docstatus": ["!=", 2]},
			fields=["service_order", "name"],
			as_list=True,
		)
	)
	for order in orders:
		order.appointment = links.get(order.name)


def _attach_technician_labels(orders):
	"""แปลง user id ของช่างทั้ง 10 ช่องเป็นชื่อจริง — query เดียว"""
	users = {order.get(field) for order in orders for field in TECHNICIAN_FIELDS if order.get(field)}
	full_names = {}
	if users:
		full_names = dict(
			frappe.get_all(
				"User", filters={"name": ["in", list(users)]}, fields=["name", "full_name"], as_list=True
			)
		)

	for order in orders:
		order.technician_labels = [
			full_names.get(order.get(field)) or order.get(field)
			for field in TECHNICIAN_FIELDS
			if order.get(field)
		]


# ── helpers ──────────────────────────────────────────────────────────────────


def _decorate_order(order, now):
	order = frappe._dict(order)
	# รับรถแล้ว (มีตราประทับ) หรือสถานะเลย Draft ไปแล้ว — ข้อมูลเก่าเปลี่ยนสถานะมือโดยไม่มีตราประทับ
	order.in_bay = bool(order.get("received_date")) or order.get("status") != "Draft"
	order.truck_label = order.get("truck_number") or order.get("vehicle") or "-"
	order.status_label = STATUS_LABELS.get(order.get("status")) or order.get("status")
	order.status_theme = STATUS_THEMES.get(order.get("status"), "grey")
	order.since_label = (
		_elapsed_label(order.get("received_date"), now) if order.get("received_date") else None
	)
	order.technician_labels = order.get("technician_labels") or []
	order.is_walk_in = not order.get("appointment")
	return order


def _unique_orders(occupants, unassigned):
	seen = {}
	for items in occupants.values():
		for item in items:
			seen.setdefault(item.name, item)
	for item in unassigned:
		seen.setdefault(item.name, item)
	return list(seen.values())


def _booking_sort_key(appointment):
	time = appointment.get("appointment_time")
	return (time is None, str(time or ""), appointment.get("name") or "")


def _time_label(value):
	"""timedelta / "HH:MM:SS" → "HH:MM" — Time field คืนเป็น timedelta จาก MariaDB"""
	if value is None or value == "":
		return "-"
	if hasattr(value, "total_seconds"):
		minutes = int(value.total_seconds()) // 60
		return f"{minutes // 60:02d}:{minutes % 60:02d}"
	return str(value)[:5]


def _elapsed_label(since, now):
	minutes = max(int((get_datetime(now) - get_datetime(since)).total_seconds() // 60), 0)
	hours, minutes = divmod(minutes, 60)
	if hours >= 24:
		days, hours = divmod(hours, 24)
		return f"{days} วัน {hours} ชม."
	if hours:
		return f"{hours} ชม. {minutes} นาที"
	return f"{minutes} นาที"


def _hours(value):
	"""ตัด .0 ท้ายจำนวนเต็ม และปัดทศนิยม 1 ตำแหน่ง — 8.0 ชม. อ่านแปลก"""
	number = round(float(value or 0), 1)
	return int(number) if number == int(number) else number


def _percent(booked, cap):
	"""ความยาวแถบความจุ (0-100) — เกิน cap ก็เต็มแถบ ส่วนเกินบอกเป็นตัวเลข OT แทน"""
	cap = float(cap or 0)
	if cap <= 0:
		return 100 if float(booked or 0) > 0 else 0
	return min(cint(float(booked or 0) / cap * 100), 100)

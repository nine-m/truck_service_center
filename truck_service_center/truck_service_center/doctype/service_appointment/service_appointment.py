# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.contacts.doctype.address.address import get_address_display
from frappe.model.document import Document
from frappe.utils import add_days, add_to_date, date_diff, flt, get_datetime, get_time, getdate

# นัดหมายที่ไม่กินความจุของช่องจอด (ตรงกับตัวกรองเดิมของ check_slot_availability)
EXCLUDED_STATUSES = ("Cancelled", "No Show")

# index ตรงกับ date.weekday() (0 = จันทร์)
WEEKDAY_FIELDS = (
	"work_day_monday",
	"work_day_tuesday",
	"work_day_wednesday",
	"work_day_thursday",
	"work_day_friday",
	"work_day_saturday",
	"work_day_sunday",
)

DAY_MODE_FULL = "เต็มวัน"
DAY_MODE_HALF = "ครึ่งวัน"
DAY_MODE_CLOSED = "หยุด"

# โหมดวันที่ไม่รู้จักหรือยังไม่ได้ตั้งค่า ให้ถือว่าเปิดเต็มวัน — site ที่ยังไม่ได้ seed
# จะได้ไม่กลายเป็นปิดทั้งสัปดาห์
DAY_MODE_MULTIPLIERS = {DAY_MODE_FULL: 1.0, DAY_MODE_HALF: 0.5, DAY_MODE_CLOSED: 0.0}

NEAR_FULL_RATIO = 0.8

CAP_SOURCE_OVERRIDE = "override"
CAP_SOURCE_HALF_DAY = DAY_MODE_HALF
CAP_SOURCE_WEEKLY_HOLIDAY = "วันหยุดประจำสัปดาห์"
CAP_SOURCE_NORMAL = "ปกติ"

STATUS_CLOSED = "ปิดทำการ"
STATUS_FULL = "เต็ม"
STATUS_NEAR_FULL = "ใกล้เต็ม"
STATUS_FREE = "ว่าง"

# ชนิดงานในตารางช่องจอด — ต้องตรงกับ options ของ Service Appointment Bay.work_type เป๊ะ
WORK_TYPE_PIT = "งานใต้ท้อง (ใช้หลุม)"
WORK_TYPE_GENERAL = "งานทั่วไป"

NO_PIT_BAY_WARNING = "มีงานที่ต้องใช้หลุมซ่อม แต่ไม่มีช่องจอดที่มีหลุมเปิดใช้งาน — ระบบรวมเป็นงานทั่วไปให้ก่อน"

# วันที่ไม่มีช่องจอดเปิดใช้งานเลย ไม่ใช่ "เต็ม" แต่คือยังตั้งค่าระบบไม่เสร็จ
NO_ACTIVE_BAY_NOTE = "ยังไม่มีช่องจอดซ่อมที่เปิดใช้งาน"

# ปฏิทินรายเดือนขอมากสุด 42 ช่อง (6 สัปดาห์) — เผื่อไว้ราว 3 เดือน แล้วกันการยิงช่วงยาวผิดปกติ
# ที่จะกวาดตาราง Service Appointment Bay ทั้งตาราง
MAX_CAPACITY_RANGE_DAYS = 93


def resolve_bay_caps(bays, day_mode, overrides):
	"""ชั่วโมงรับงานที่มีผลจริงของแต่ละช่องจอดในวันหนึ่ง

	ลำดับความสำคัญ: override ที่ระบุช่องจอด > override ที่เว้นช่องจอดว่าง (มีผลทุกช่อง)
	> ชั่วโมงรับงานประจำของช่องจอด คูณ ตัวคูณของโหมดวัน (เต็มวัน 1, ครึ่งวัน 0.5, หยุด 0)

	override > 0 บนวันหยุดประจำสัปดาห์จึงเปิดวันนั้นได้ และ override 0 ปิดวันทำการได้
	"""
	multiplier = DAY_MODE_MULTIPLIERS.get(day_mode, 1.0)

	by_bay = {}
	global_override = None
	for override in overrides or []:
		bay = override.get("service_bay")
		if bay:
			by_bay[bay] = override
		elif global_override is None:
			global_override = override

	caps = {}
	for bay in bays or []:
		name = bay.get("name")
		override = by_bay.get(name) or global_override
		if override is not None:
			cap = flt(override.get("capacity_hours"))
			source = CAP_SOURCE_OVERRIDE
			reason = override.get("reason")
		else:
			cap = flt(bay.get("daily_capacity_hours")) * multiplier
			reason = None
			if multiplier == 0:
				source = CAP_SOURCE_WEEKLY_HOLIDAY
			elif multiplier < 1:
				source = CAP_SOURCE_HALF_DAY
			else:
				source = CAP_SOURCE_NORMAL

		caps[name] = {
			"cap": flt(cap, 2),
			"source": source,
			"is_closed": flt(cap) <= 0,
			"reason": reason,
		}

	return caps


def availability_status(cap, booked, is_closed=False):
	"""สถานะที่เอาไปโชว์เป็น badge: ปิดทำการ / เต็ม / ใกล้เต็ม / ว่าง"""
	if is_closed:
		return STATUS_CLOSED

	cap = flt(cap)
	booked = flt(booked)

	if cap <= 0 or booked >= cap:
		return STATUS_FULL
	if booked >= cap * NEAR_FULL_RATIO:
		return STATUS_NEAR_FULL
	return STATUS_FREE


def build_day_rows(bays, caps, booked_hours):
	"""แถวสถานะต่อช่องจอดของวันหนึ่ง — รูปเดียวกับที่ dialog/ฟอร์ม/ปฏิทินใช้ร่วมกัน

	แยกออกมาเป็น pure function เพื่อให้ get_bay_availability (ทีละวัน) กับ
	get_capacity_range (ทีละช่วง) ประกอบแถวด้วยโค้ดชุดเดียวกัน ไม่มีทางเพี้ยนจากกัน

	free ติดลบได้ตามเดิม — ส่วนที่เกินคือชั่วโมง OT ที่จองไปแล้ว ไม่ใช่ศูนย์
	"""
	rows = []
	for bay in bays or []:
		name = bay.get("name")
		cap_info = caps.get(name) or {}
		cap = flt(cap_info.get("cap"))
		booked = flt((booked_hours or {}).get(name), 2)
		rows.append(
			{
				"bay": name,
				"bay_name": bay.get("bay_name"),
				"has_pit": int(bay.get("has_pit") or 0),
				"cap": cap,
				"cap_source": cap_info.get("source"),
				"is_closed": bool(cap_info.get("is_closed")),
				"reason": cap_info.get("reason"),
				"booked": booked,
				"free": flt(cap - booked, 2),
				"status": availability_status(cap, booked, cap_info.get("is_closed")),
			}
		)

	return rows


def build_day_notes(day_mode, overrides):
	"""ข้อความอธิบายภาพรวมของวัน (โหมดวัน + override ที่มีผลทุกช่อง)

	รับ overrides ทั้งชุดของวันนั้น เพราะต้องหา override ที่เว้นช่องจอดว่างเอง
	ซึ่งเป็นตัวเดียวที่กระทบทุกช่องจอดจนควรบอกในระดับวัน
	"""
	notes = []
	if day_mode == DAY_MODE_CLOSED:
		notes.append("วันนี้ตั้งค่าไว้เป็นวันหยุดประจำสัปดาห์")
	elif day_mode == DAY_MODE_HALF:
		notes.append("วันนี้ทำครึ่งวัน — ชั่วโมงรับงานของทุกช่องจอดเหลือครึ่งเดียว")

	global_override = next((o for o in overrides or [] if not o.get("service_bay")), None)
	if global_override is not None:
		hours = flt(global_override.get("capacity_hours"), 2)
		reason = global_override.get("reason")
		suffix = f" ({reason})" if reason else ""
		if hours <= 0:
			notes.append(f"มีรายการปิดทำการทุกช่องจอดในวันนี้{suffix}")
		else:
			notes.append(f"มีรายการปรับชั่วโมงรับงานของทุกช่องจอดเป็น {hours} ชม.{suffix}")

	return " • ".join(notes)


def summarize_day(rows, day_note=""):
	"""ยอดรวมระดับวัน — ตัวเลขชุดเดียวที่ฟอร์ม ปฏิทิน และคำเตือนใช้ร่วมกัน

	free clamp ต่อช่อง (ไม่ใช่ cap รวม ลบ booked รวม) เพราะชั่วโมงย้ายข้ามช่องจอดไม่ได้:
	BAY-01 10/8 + BAY-02 2/8 คือ OT 2 ชม. และยังรับได้อีก 6 ชม. ไม่ใช่ "12/16 ยังไม่เต็ม"
	— ตรงกับที่ build_capacity_warnings เตือนเป็นรายช่องอยู่แล้ว

	status ดูจาก cap - free (ชั่วโมงที่ถูกกินไปจริงในเชิง "ยังจองได้ไหม") ส่วน over ตอบ
	คนละคำถามคือ OT ที่เกิดไปแล้วเท่าไร — 12/8 + 7/8 จึงเป็น "ใกล้เต็ม" (ยังจองได้ 1 ชม.)
	ทั้งที่ booked 19 เกิน cap 16 ไปแล้ว

	วันที่ไม่มีช่องจอดเลย availability_status(0, 0) จะตอบ "เต็ม" ซึ่งสื่อผิด จึงตอบปิดทำการ
	พร้อม note บอกสาเหตุจริงแทน
	"""
	rows = rows or []
	cap = flt(sum(flt(row.get("cap")) for row in rows), 2)
	booked = flt(sum(flt(row.get("booked")) for row in rows), 2)
	free = flt(sum(max(flt(row.get("cap")) - flt(row.get("booked")), 0.0) for row in rows), 2)
	over = flt(sum(max(flt(row.get("booked")) - flt(row.get("cap")), 0.0) for row in rows), 2)

	has_bays = bool(rows)
	is_closed = has_bays and all(row.get("is_closed") for row in rows)

	if not has_bays:
		status = STATUS_CLOSED
	else:
		status = availability_status(cap, flt(cap - free, 2), is_closed)

	return {
		"cap": cap,
		"booked": booked,
		"free": free,
		"over": over,
		"status": status,
		"is_closed": is_closed,
		"has_bays": has_bays,
		"day_note": day_note or ("" if has_bays else NO_ACTIVE_BAY_NOTE),
	}


def fold_booked_hours(appointments, bay_rows):
	"""รวมชั่วโมงที่จองแล้วเป็น {"YYYY-MM-DD": {ช่องจอด: ชั่วโมง}}

	pure ล้วน เพื่อให้เทสต์ครอบตรรกะการรวมได้โดยไม่ต้อง insert Service Appointment จริง
	(ซึ่งบังคับ customer/vehicle และ validate เต็มใบ)

	key วันที่เป็นสตริงเสมอ จะได้เป็นชนิดเดียวกันทั้งตอน lookup ในลูปและตอนส่งออกเป็น JSON
	"""
	date_by_name = {row.get("name"): str(getdate(row.get("appointment_date"))) for row in appointments or []}

	booked = {}
	for row in bay_rows or []:
		bay = row.get("service_bay")
		if not bay:
			continue
		date = date_by_name.get(row.get("parent"))
		if date is None:
			continue
		per_bay = booked.setdefault(date, {})
		per_bay[bay] = per_bay.get(bay, 0.0) + flt(row.get("allocated_hours"))

	return booked


def compute_allocation(pit_hours, general_hours, availability):
	"""จัดช่องจอดให้นัดหมายหนึ่งใบ — สูงสุด 2 แถว (งานหลุม 1 + งานทั่วไป 1)

	รถย้ายช่องจอดได้ครั้งเดียว จึงไม่กระจายงานลง 3 ช่องขึ้นไป ช่องเดียวรับได้ทั้งสองส่วน
	(เป็น 2 แถวแยกตามประเภทงาน) ไม่ throw ในทุกกรณี — ความจุที่ไม่พอเป็นเรื่องของ
	build_capacity_warnings ที่เตือนอย่างเดียวตามที่ผู้ใช้ยืนยัน
	"""
	allocations = []
	warnings = []

	pit_hours = flt(pit_hours)
	general_hours = flt(general_hours)
	if not availability or (pit_hours <= 0 and general_hours <= 0):
		return allocations, warnings

	free = {row.get("bay"): flt(row.get("free")) for row in availability}

	if pit_hours > 0:
		pit_bays = [row for row in availability if row.get("has_pit")]
		if pit_bays:
			# ช่องที่รับไหวมาก่อน แล้วค่อยดูช่องที่ว่างที่สุด
			chosen = max(pit_bays, key=lambda row: (free[row["bay"]] >= pit_hours, free[row["bay"]]))
			allocations.append(
				{
					"service_bay": chosen["bay"],
					"work_type": WORK_TYPE_PIT,
					"allocated_hours": flt(pit_hours, 2),
				}
			)
			# หักช่องที่เพิ่งจองไปก่อน จะได้ไม่เลือกช่องเดิมทั้งที่เต็มแล้ว
			free[chosen["bay"]] -= pit_hours
		else:
			warnings.append(NO_PIT_BAY_WARNING)
			general_hours += pit_hours

	if general_hours > 0:
		# ช่องที่รับไหว > ช่องที่ไม่มีหลุม (กันหลุมไว้ให้งานที่ต้องใช้จริง) > ช่องที่ว่างที่สุด
		chosen = max(
			availability,
			key=lambda row: (
				free[row["bay"]] >= general_hours,
				not row.get("has_pit"),
				free[row["bay"]],
			),
		)
		allocations.append(
			{
				"service_bay": chosen["bay"],
				"work_type": WORK_TYPE_GENERAL,
				"allocated_hours": flt(general_hours, 2),
			}
		)

	return allocations, warnings


def build_capacity_warnings(doc, availability, cap_map, pit_service_types):
	"""ข้อความเตือนเรื่องความจุ — คืนเป็น list ไม่ throw (ผู้ใช้ยืนยันว่าเตือนอย่างเดียว)

	แยกเป็นฟังก์ชัน pure ระดับ module แบบเดียวกับ get_bay_warnings ของใบสั่งงาน
	เพื่อให้ validate, endpoint ตรวจก่อนบันทึก และเทสต์ ใช้ตรรกะชุดเดียวกัน
	"""
	warnings = []
	date = doc.get("appointment_date")

	if not availability:
		return ["ยังไม่มีช่องจอดซ่อมที่เปิดใช้งาน — ระบบจัดช่องจอดให้ไม่ได้"]

	if any(
		(cap_map.get(row.get("bay")) or {}).get("source") == CAP_SOURCE_WEEKLY_HOLIDAY for row in availability
	):
		warnings.append(f"วันที่ {date} เป็นวันหยุดประจำสัปดาห์ตามการตั้งค่า — งานที่จองถือเป็นงาน OT")

	rows = doc.get("bay_allocations") or []
	if not rows:
		return warnings

	hours_by_bay = {}
	for row in rows:
		bay = row.get("service_bay")
		hours_by_bay[bay] = hours_by_bay.get(bay, 0.0) + flt(row.get("allocated_hours"))

	by_bay = {row.get("bay"): row for row in availability}

	for bay, hours in hours_by_bay.items():
		info = by_bay.get(bay)
		if info is None:
			warnings.append(f"ช่องจอด {bay} ไม่อยู่ในรายการช่องจอดที่เปิดใช้งานของวันที่ {date}")
			continue

		cap_info = cap_map.get(bay) or {}
		if cap_info.get("is_closed") and cap_info.get("source") == CAP_SOURCE_OVERRIDE:
			reason = cap_info.get("reason")
			suffix = f" ({reason})" if reason else ""
			warnings.append(f"ช่องจอด {bay} ถูกปิดทำการวันที่ {date}{suffix} — งานที่จองถือเป็นงาน OT")

		cap = flt(info.get("cap"))
		total = flt(info.get("booked")) + hours
		if cap > 0 and total > cap:
			warnings.append(
				f"ช่องจอด {bay} วันที่ {date} จะใช้ {flt(total, 2)}/{flt(cap, 2)} ชม. — ส่วนเกินเป็นงาน OT"
			)
		if cap > 0 and hours > cap:
			warnings.append(
				f"งานนี้ใช้เวลา {flt(hours, 2)} ชม. เกินชั่วโมงรับงานต่อวันของช่องจอด {bay} "
				f"({flt(cap, 2)} ชม.) — งานอาจทำข้ามวัน"
			)

	for row in rows:
		if row.get("work_type") != WORK_TYPE_PIT:
			continue
		info = by_bay.get(row.get("service_bay"))
		if info and not info.get("has_pit"):
			warnings.append(f"งานใต้ท้องถูกจัดลงช่องจอด {row.get('service_bay')} ซึ่งไม่มีหลุมซ่อม")

	pit_hours, _general_hours = split_pit_hours(doc, pit_service_types)
	if pit_hours > 0 and not any(row.get("has_pit") for row in availability):
		warnings.append(NO_PIT_BAY_WARNING)

	allocated = flt(sum(flt(row.get("allocated_hours")) for row in rows), 2)
	duration = flt(doc.get("estimated_duration"), 2)
	if abs(allocated - duration) > 0.01:
		warnings.append(
			f"ชั่วโมงในตารางช่องจอดรวม {allocated} ชม. ไม่ตรงกับระยะเวลางาน {duration} ชม. "
			"— กดปุ่ม 'จัด Bay ใหม่' ถ้าต้องการให้ระบบจัดใหม่"
		)

	return warnings


def get_bay_availability(date, exclude_appointment=None):
	"""ฟังก์ชัน availability เดียวของระบบ — ใช้ทั้ง dialog, การจัดช่องจอด และคำเตือน

	ดึงข้อมูลเป็น batch ทุกชุด (ช่องจอด / override / ชั่วโมงที่จองแล้ว) ไม่มี N+1
	"""
	date = getdate(date)

	bays = frappe.get_all(
		"Service Bay",
		filters={"is_active": 1},
		fields=["name", "bay_name", "has_pit", "daily_capacity_hours"],
		order_by="bay_name asc",
	)

	settings = frappe.get_cached_doc("Truck Service Center Settings")
	day_mode = settings.get(WEEKDAY_FIELDS[date.weekday()])

	overrides = frappe.get_all(
		"Bay Capacity Override",
		filters={"override_date": date},
		fields=["service_bay", "capacity_hours", "reason"],
		order_by="creation asc",
	)

	caps = resolve_bay_caps(bays, day_mode, overrides)
	booked_hours = get_booked_hours(date, exclude_appointment)

	rows = build_day_rows(bays, caps, booked_hours)
	day_note = build_day_notes(day_mode, overrides)

	return {
		"date": str(date),
		"bays": rows,
		"caps": caps,
		"day_closed": bool(rows) and all(row["is_closed"] for row in rows),
		"day_note": day_note,
		"summary": summarize_day(rows, day_note),
	}


def get_booked_hours_range(start, end, exclude_appointment=None):
	"""ชั่วโมงที่ถูกจองไว้แล้วของทุกช่องจอดตลอดช่วงวัน — 2 query ไม่ว่าช่วงยาวแค่ไหน

	ตัวกรองนัดหมายตรงกับ check_slot_availability เดิม: ยังไม่ถูก cancel, สถานะไม่ใช่
	Cancelled/No Show และไม่นับตัวเอง — ฉบับร่างนับด้วยเหมือนเดิม

	นี่คือที่เดียวที่ตัวกรองนี้อยู่ get_booked_hours (รายวัน) เรียกตัวนี้ต่อ จะได้ไม่ต้อง
	คอยไล่ sync เงื่อนไขสองชุดให้ตรงกัน
	"""
	start = getdate(start)
	end = getdate(end)

	filters = {
		"appointment_date": ["between", [start, end]],
		"docstatus": ["!=", 2],
		"status": ["not in", list(EXCLUDED_STATUSES)],
	}
	if exclude_appointment:
		filters["name"] = ["!=", exclude_appointment]

	appointments = frappe.get_all("Service Appointment", filters=filters, fields=["name", "appointment_date"])
	if not appointments:
		return {}

	bay_rows = frappe.get_all(
		"Service Appointment Bay",
		filters={
			"parenttype": "Service Appointment",
			"parent": ["in", [row.name for row in appointments]],
		},
		fields=["parent", "service_bay", "allocated_hours"],
	)

	return fold_booked_hours(appointments, bay_rows)


def get_booked_hours(date, exclude_appointment=None):
	"""ชั่วโมงที่ถูกจองไว้แล้วของแต่ละช่องจอดในวันหนึ่ง (ฉบับวันเดียวของ range เวอร์ชัน)"""
	date = getdate(date)

	return get_booked_hours_range(date, date, exclude_appointment).get(str(date), {})


def get_pit_service_types(doc):
	"""ชื่องานในเอกสารที่ต้องใช้หลุมซ่อม — query เดียว (mirror _get_pit_warnings ของใบสั่งงาน)"""
	names = {row.get("service_type") for row in (doc.get("service_types") or []) if row.get("service_type")}
	if not names:
		return set()

	return set(
		frappe.get_all(
			"Service Type",
			filters={"name": ["in", list(names)], "requires_pit": 1},
			pluck="name",
		)
	)


def get_capacity_warnings(doc):
	"""ประกอบข้อมูลจาก DB แล้วส่งต่อให้ build_capacity_warnings ตัดสิน"""
	if not doc.get("appointment_date"):
		return []

	availability = get_bay_availability(doc.get("appointment_date"), exclude_appointment=doc.get("name"))

	return build_capacity_warnings(
		doc, availability["bays"], availability["caps"], get_pit_service_types(doc)
	)


def dedupe(messages):
	"""ตัดข้อความซ้ำโดยคงลำดับเดิม (คำเตือนชุดจัดช่องจอดกับชุดความจุทับกันได้)"""
	seen = set()
	unique = []
	for message in messages:
		if message in seen:
			continue
		seen.add(message)
		unique.append(message)
	return unique


def split_pit_hours(doc, pit_service_types):
	"""แยกชั่วโมงงานเป็น (งานที่ต้องใช้หลุม, งานทั่วไป)

	โครงเดียวกับ ServiceAppointment.calculate_estimated_duration ด้านล่าง — ต้องแก้คู่กัน
	ผลรวมของสองค่าที่คืนต้องเท่ากับ estimated_duration เสมอ มิฉะนั้นจะขึ้นคำเตือน stale

	แพ็คเกจที่กรอกเวลาซ่อมจริงไว้ ใช้ค่านั้นเป็นเพดานของทั้งแพ็คเกจ ส่วนที่เป็นงานหลุม
	จึงถูก cap ด้วยเวลาซ่อมจริงเช่นกัน (แถวหลุมรวม 5 ชม. ในแพ็คเกจ 2 ชม. → หลุม 2 ทั่วไป 0)
	"""
	by_package = {}
	by_package_pit = {}
	loose_pit = 0.0
	loose_general = 0.0

	for row in doc.get("service_types") or []:
		hours = flt(row.get("estimated_time"))
		needs_pit = row.get("service_type") in pit_service_types
		package = row.get("service_package")
		if package:
			by_package[package] = by_package.get(package, 0.0) + hours
			if needs_pit:
				by_package_pit[package] = by_package_pit.get(package, 0.0) + hours
		elif needs_pit:
			loose_pit += hours
		else:
			loose_general += hours

	pit_total = loose_pit
	general_total = loose_general
	for row in doc.get("service_packages") or []:
		rows_total = by_package.pop(row.get("service_package"), 0.0)
		rows_pit = by_package_pit.pop(row.get("service_package"), 0.0)
		effective = flt(row.get("repair_time_hours")) or rows_total
		pit_part = min(rows_pit, effective)
		pit_total += pit_part
		general_total += effective - pit_part

	# แถวงานที่แพ็คเกจต้นทางถูกลบไปแล้ว ยังต้องนับเวลาให้อยู่
	for package, rows_total in by_package.items():
		rows_pit = by_package_pit.pop(package, 0.0)
		pit_total += rows_pit
		general_total += rows_total - rows_pit

	return flt(pit_total, 2), flt(general_total, 2)


class ServiceAppointment(Document):
	def validate(self):
		self.set_address_display()
		self.validate_appointment_datetime()
		self.sync_vehicle_info()
		self.calculate_estimated_duration()
		self.calculate_totals()
		self.set_appointment_datetimes()
		self.allocate_bays()
		self.warn_capacity_issues()

	def calculate_estimated_duration(self):
		"""ระยะเวลานัดหมาย = เวลาซ่อมจริงของแต่ละแพ็คเกจ + เวลาของงานที่ไม่ได้มาจากแพ็คเกจ

		แพ็คเกจที่กรอก repair_time_hours ไว้ (เวลาซ่อมจริงแบบ wall-clock) จะใช้ค่านั้นแทน
		ผลรวมเวลาของงานในแพ็คเกจ เพราะงานหลายอย่างในแพ็คเกจทำขนานกันได้ ผลรวมจึงยาวเกินจริง
		แพ็คเกจที่ยังไม่ได้กรอกจะถอยไปใช้ผลรวมเวลาของงานในแพ็คเกจนั้นตามเดิม

		ใช้ .pop กันนับซ้ำ และบวกเศษที่เหลือใน by_package กลับเข้าไป เพื่อครอบคลุมกรณีที่
		แถวแพ็คเกจถูกลบไปแล้วแต่แถวงานของมันยังอยู่

		โครงเดียวกับ split_pit_hours ด้านบน — ต้องแก้คู่กัน
		"""
		by_package = {}
		loose = 0.0
		for row in self.service_types or []:
			if row.service_package:
				by_package[row.service_package] = by_package.get(row.service_package, 0.0) + flt(
					row.estimated_time
				)
			else:
				loose += flt(row.estimated_time)

		total = loose
		for row in self.service_packages or []:
			rows_total = by_package.pop(row.service_package, 0.0)
			total += flt(row.repair_time_hours) or rows_total

		# แถวงานที่แพ็คเกจต้นทางถูกลบไปแล้ว ยังต้องนับเวลาให้อยู่
		total += sum(by_package.values())

		self.estimated_duration = flt(total, 2)

	def calculate_totals(self):
		"""คำนวณยอดรวมราคาจาก service_types และ service_items"""
		# ปัดเศษทุกค่าเป็นทศนิยม 2 ตำแหน่ง มิฉะนั้นค่าที่คำนวณใหม่ (เช่น 999.8299999999999)
		# จะไม่ตรงกับค่าที่ฐานข้อมูลปัดเก็บไว้ (999.83) และทำให้ submit ไม่ผ่าน
		# ด้วย error "Cannot Update After Submit"
		# รวมค่าแรง
		self.total_labor_charges = flt(sum(flt(row.labor_charges) for row in (self.service_types or [])), 2)

		# รวมค่าอะไหล่ (คำนวณ amount ของแต่ละรายการด้วย)
		for item in self.service_items or []:
			item.amount = flt(flt(item.qty) * flt(item.rate), 2)
		self.total_parts_amount = flt(sum(flt(row.amount) for row in (self.service_items or [])), 2)

		# ยอดรวมทั้งหมด
		self.total_amount = flt(flt(self.total_labor_charges) + flt(self.total_parts_amount), 2)

	def set_address_display(self):
		"""ตั้งค่าการแสดงผลที่อยู่สำหรับ billing และ shipping address"""
		if self.customer_address:
			self.address_display = get_address_display(self.customer_address)
		else:
			self.address_display = ""

		if self.shipping_address_name:
			self.shipping_address = get_address_display(self.shipping_address_name)
		else:
			self.shipping_address = ""

	def validate_appointment_datetime(self):
		"""ตรวจสอบวันเวลานัดหมายต้องไม่อยู่ในอดีต"""
		if self.appointment_date:
			from frappe.utils import getdate, today

			if getdate(self.appointment_date) < getdate(today()):
				frappe.throw("ไม่สามารถนัดหมายย้อนหลังได้")

	def sync_vehicle_info(self):
		"""ซิงค์ข้อมูลจาก Vehicle: license_plate และ customer"""
		if not self.vehicle:
			return

		plate = frappe.db.get_value("Vehicle", self.vehicle, "license_plate")
		if plate and self.license_plate != plate:
			self.license_plate = plate

		if not self.customer:
			cust = frappe.db.get_value("Vehicle", self.vehicle, "customer")
			if cust:
				self.customer = cust

	def set_appointment_datetimes(self):
		"""คำนวณ start/end datetime สำหรับปฏิทิน

		ไม่ระบุเวลานัด = กิจกรรมทั้งวัน (all_day) ตามที่ผู้ใช้ยืนยันว่าเวลาไม่บังคับ
		ระบุเวลา = เริ่มตามเวลานัด ยาวเท่าระยะเวลางาน (ไม่มีระยะเวลาให้ถือ 1 ชม.)
		"""
		if self.appointment_date and self.appointment_time:
			self.appointment_start = get_datetime(
				f"{getdate(self.appointment_date)} {get_time(self.appointment_time)}"
			)
			self.appointment_end = add_to_date(
				self.appointment_start, hours=flt(self.estimated_duration) or 1.0
			)
			self.all_day = 0
			return

		self.appointment_start = self.appointment_date
		self.appointment_end = self.appointment_date
		self.all_day = 1

	def allocate_bays(self):
		"""จัดช่องจอดให้อัตโนมัติ เฉพาะตอนที่ตารางยังว่าง

		ethos เดียวกับ apply_default_bay ของใบสั่งงาน: เติมให้เฉพาะช่องว่าง ไม่ทับค่าที่
		แก้มือไว้ — ตารางที่ไม่ว่างแล้วทำให้ validate รอบสอง (on_submit เรียก save)
		ไม่จัดซ้ำเองด้วย ปุ่ม "จัด Bay ใหม่" คือทางจัดใหม่แบบตั้งใจ
		"""
		if self.bay_allocations:
			return
		if not self.appointment_date or flt(self.estimated_duration) <= 0:
			return

		availability = get_bay_availability(self.appointment_date, exclude_appointment=self.name)
		pit_hours, general_hours = split_pit_hours(self, get_pit_service_types(self))
		# คำเตือนจากการจัดช่องจอดไม่ msgprint ที่นี่ — warn_capacity_issues ครอบคลุมให้แล้ว
		allocations, _warnings = compute_allocation(pit_hours, general_hours, availability["bays"])
		if not allocations:
			return

		for row in allocations:
			self.append("bay_allocations", row)

		summary = ", ".join(
			f"{row['service_bay']} — {row['work_type']} {flt(row['allocated_hours'], 2)} ชม."
			for row in allocations
		)
		frappe.msgprint(f"จัดช่องจอดอัตโนมัติ: {summary}", indicator="green")

	def warn_capacity_issues(self):
		"""เตือนเรื่องความจุอย่างเดียว ไม่บล็อกการบันทึก (ตามที่ผู้ใช้ยืนยัน)

		msgprint ทุกข้อความเสมอ เพื่อให้ path ที่ไม่ผ่าน desk (API/พอร์ทัล) ยังเห็นคำเตือน
		"""
		for warning in get_capacity_warnings(self):
			frappe.msgprint(warning, indicator="orange")

	def on_submit(self):
		"""เมื่อยืนยันนัดหมาย"""
		self.status = "Confirmed"
		self.save()

	def on_cancel(self):
		"""เมื่อยกเลิกนัดหมาย"""
		self.status = "Cancelled"
		self.save()

	def create_service_order(self):
		"""สร้าง Service Order จากนัดหมาย"""
		if self.service_order:
			frappe.throw("มีการสร้าง Service Order ไปแล้ว")

		service_order = frappe.new_doc("Service Order")
		service_order.customer = self.customer
		service_order.vehicle = self.vehicle
		service_order.service_date = self.appointment_date
		service_order.technician = self.assigned_technician

		# ช่องจอดหลัก = ช่องที่จองชั่วโมงไว้มากที่สุด ส่วนแถวงานได้ช่องตามประเภทงานของมัน
		bay_by_work_type = {}
		for row in self.bay_allocations or []:
			bay_by_work_type.setdefault(row.work_type, row.service_bay)

		main_bay = None
		if self.bay_allocations:
			main_bay = max(self.bay_allocations, key=lambda row: flt(row.allocated_hours)).service_bay
			service_order.service_bay = main_bay

		pit_service_types = get_pit_service_types(self) if self.bay_allocations else set()

		# ส่งที่อยู่ไปยัง Service Order
		if self.customer_address:
			service_order.customer_address = self.customer_address
			service_order.address_display = self.address_display
		if self.shipping_address_name:
			service_order.shipping_address_name = self.shipping_address_name
			service_order.shipping_address = self.shipping_address

		# รวม customer_complaints จาก repair_cause และ service_remark
		complaints = []
		if self.repair_cause:
			complaints.append(f"สาเหตุที่ซ่อม: {self.repair_cause}")
		if self.service_remark:
			complaints.append(f"หมายเหตุ: {self.service_remark}")
		if complaints:
			service_order.customer_complaints = "\n".join(complaints)

		# ดึงข้อมูลไมล์จากรถปัจจุบัน
		if self.vehicle:
			vehicle_data = frappe.db.get_value("Vehicle", self.vehicle, ["current_mileage"], as_dict=1) or {}
			if vehicle_data.get("current_mileage"):
				service_order.current_mileage = vehicle_data.get("current_mileage")

		# คัดลอกแพ็คเกจบริการ (หลาย package)
		for pkg_row in self.service_packages or []:
			service_order.append(
				"service_packages",
				{
					"service_package": pkg_row.service_package,
					"package_code": pkg_row.package_code,
					"package_name": pkg_row.package_name,
					"package_rate": pkg_row.package_rate,
					"discount_percent": pkg_row.discount_percent,
				},
			)

		# คัดลอก service types จากตาราง (ถ้ามี)
		if self.service_types:
			for st_row in self.service_types:
				work_type = WORK_TYPE_PIT if st_row.service_type in pit_service_types else WORK_TYPE_GENERAL
				service_order.append(
					"service_types",
					{
						"service_type": st_row.service_type,
						"service_type_group": st_row.service_type_group,
						"maintenance_type": st_row.maintenance_type,
						"estimated_time": st_row.estimated_time,
						"labor_charges": st_row.labor_charges,
						"service_package": st_row.service_package,
						"remark": st_row.remark,
						"service_bay": bay_by_work_type.get(work_type) or main_bay,
					},
				)
		# คัดลอก service items (อะไหล่)
		for item_row in self.service_items or []:
			service_order.append(
				"service_items",
				{
					"item_code": item_row.item_code,
					"item_name": item_row.item_name,
					"qty": item_row.qty,
					"uom": item_row.uom,
					"rate": item_row.rate,
					"service_package": item_row.service_package,
					"service_type": item_row.service_type,
				},
			)

		service_order.insert()

		# เก็บ reference
		self.db_set("service_order", service_order.name)
		self.db_set("status", "In Progress")

		frappe.msgprint(f"สร้าง Service Order: {service_order.name}")

		return service_order.name


@frappe.whitelist()
def get_calendar_events(doctype, start, end, field_map, filters=None, fields=None):
	"""Wrapper รอบ frappe.desk.calendar.get_events — ฝั่ง client ส่ง start/end เป็น
	datetime string ตาม system timezone แต่ get_events ประกาศรับ datetime.date
	ทำให้โดน pydantic ปฏิเสธเมื่อเวลาไม่ใช่ 00:00:00 จึงตัดเวลาทิ้งก่อนส่งต่อ"""
	from frappe.desk.calendar import get_events

	return get_events(doctype, getdate(start), getdate(end), field_map, filters, fields)


@frappe.whitelist()
def create_service_order_from_appointment(appointment):
	"""สร้าง Service Order จากนัดหมาย - สำหรับเรียกจาก client"""
	doc = frappe.get_doc("Service Appointment", appointment)
	doc.check_permission("write")
	return doc.create_service_order()


@frappe.whitelist()
def get_bay_day_status(date, exclude_appointment=None):
	"""สถานะช่องจอดของวันหนึ่ง สำหรับ dialog ตอนเลือกวันที่นัดหมาย"""
	frappe.has_permission("Service Appointment", "read", throw=True)

	return get_bay_availability(date, exclude_appointment=exclude_appointment)


@frappe.whitelist()
def get_capacity_range(start, end):
	"""ความจุรายวันตลอดช่วง สำหรับแปะตัวเลขลงทุกช่องของปฏิทิน

	ปฏิทินเปิดหนึ่งครั้ง = 4 query + settings ที่ cache ไว้ ไม่ว่าช่วงจะยาวแค่ไหน
	ห้ามวนเรียก get_bay_availability รายวันเด็ดขาด — เดือนหนึ่งจะกลายเป็น 42 คูณ 4 query

	รูปแถวใน "bays" มาจาก build_day_rows ตัวเดียวกับที่ฟอร์มใช้ ตัวเลขของปฏิทินกับฟอร์ม
	จึงตรงกันโดยโครงสร้าง ไม่ใช่เพราะบังเอิญเขียนเหมือนกัน
	"""
	frappe.has_permission("Service Appointment", "read", throw=True)

	start = getdate(start)
	end = getdate(end)

	if end < start:
		frappe.throw("ช่วงวันที่ไม่ถูกต้อง — วันสิ้นสุดต้องไม่มาก่อนวันเริ่ม")
	if date_diff(end, start) > MAX_CAPACITY_RANGE_DAYS:
		frappe.throw(f"ขอข้อมูลความจุได้ครั้งละไม่เกิน {MAX_CAPACITY_RANGE_DAYS} วัน")

	bays = frappe.get_all(
		"Service Bay",
		filters={"is_active": 1},
		fields=["name", "bay_name", "has_pit", "daily_capacity_hours"],
		order_by="bay_name asc",
	)

	settings = frappe.get_cached_doc("Truck Service Center Settings")

	overrides = frappe.get_all(
		"Bay Capacity Override",
		filters={"override_date": ["between", [start, end]]},
		fields=["override_date", "service_bay", "capacity_hours", "reason"],
		order_by="override_date asc, creation asc",
	)

	# ต้องคงลำดับ creation ไว้ในแต่ละวัน — resolve_bay_caps เลือก global override ตัวแรกที่เจอ
	overrides_by_date = {}
	for override in overrides:
		overrides_by_date.setdefault(str(getdate(override.override_date)), []).append(override)

	booked = get_booked_hours_range(start, end)

	days = {}
	date = start
	while date <= end:
		key = str(date)
		day_mode = settings.get(WEEKDAY_FIELDS[date.weekday()])
		day_overrides = overrides_by_date.get(key, [])
		caps = resolve_bay_caps(bays, day_mode, day_overrides)
		rows = build_day_rows(bays, caps, booked.get(key, {}))
		days[key] = {
			"summary": summarize_day(rows, build_day_notes(day_mode, day_overrides)),
			"bays": rows,
		}
		date = getdate(add_days(date, 1))

	return {"start": str(start), "end": str(end), "days": days}


@frappe.whitelist()
def check_appointment_capacity(doc):
	"""ตรวจความจุล่วงหน้าจากเอกสารทั้งใบ โดยไม่เขียนอะไรลงฐานข้อมูล

	รับเอกสารทั้งใบเพราะใบใหม่ยังไม่มี name ให้ overlay ทีละฟิลด์แบบ check_bay_conflicts
	ของใบสั่งงานได้ และคำนวณระยะเวลาใหม่ฝั่ง server เสมอ ไม่เชื่อค่าที่ client ส่งมา

	ใช้ทั้งปุ่ม "จัด Bay ใหม่" และ confirm ก่อนบันทึกเมื่อจะใช้เกินความจุ
	"""
	frappe.has_permission("Service Appointment", "read", throw=True)

	if isinstance(doc, str):
		doc = json.loads(doc)

	appointment = frappe.get_doc(doc)
	appointment.calculate_estimated_duration()

	availability = get_bay_availability(
		appointment.appointment_date, exclude_appointment=appointment.get("name")
	)
	pit_service_types = get_pit_service_types(appointment)

	warnings = []
	if not appointment.bay_allocations:
		pit_hours, general_hours = split_pit_hours(appointment, pit_service_types)
		allocations, alloc_warnings = compute_allocation(pit_hours, general_hours, availability["bays"])
		for row in allocations:
			appointment.append("bay_allocations", row)
		warnings.extend(alloc_warnings)

	warnings.extend(
		build_capacity_warnings(appointment, availability["bays"], availability["caps"], pit_service_types)
	)

	return {
		"allocations": [
			{
				"service_bay": row.service_bay,
				"work_type": row.work_type,
				"allocated_hours": flt(row.allocated_hours, 2),
			}
			for row in appointment.bay_allocations or []
		],
		"warnings": dedupe(warnings),
		"availability": availability,
	}


@frappe.whitelist()
def backfill_license_plate():
	"""เติมค่าทะเบียนรถใน Service Appointment ที่ยังว่างอยู่"""
	frappe.only_for(("System Manager", "Service Manager"))
	docs = frappe.get_all(
		"Service Appointment",
		filters={"vehicle": ["!=", None], "license_plate": ["in", [None, ""]]},
		fields=["name", "vehicle"],
	)
	updated = 0
	for d in docs:
		plate = frappe.db.get_value("Vehicle", d["vehicle"], "license_plate")
		if plate:
			frappe.db.set_value("Service Appointment", d["name"], "license_plate", plate)
			updated += 1
	return {"updated": updated}


@frappe.whitelist()
def get_party_shipping_address(doctype, name):
	"""Wrapper for erpnext get_party_shipping_address"""
	from erpnext.accounts.party import get_party_shipping_address as _get_party_shipping_address

	return _get_party_shipping_address(doctype, name)

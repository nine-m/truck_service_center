# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""สาขา (Service Branch) — ทุกสาขาอยู่ใต้ Company เดียวกัน

ที่เดียวที่รู้ว่า "เอกสารนี้ / ผู้ใช้คนนี้ อยู่สาขาไหน" และ "ค่าตั้งของสาขานี้คืออะไร"

- ค่าตั้ง: get_branch_settings(branch) คืน Truck Service Center Settings ที่ทับด้วยค่าของสาขา
  (เฉพาะฟิลด์ใน BRANCH_OVERRIDE_FIELDS ที่สาขาตั้งไว้) ผู้เรียกจึงอ่านชื่อฟิลด์เดิมได้เลย
- สิทธิ์: สาขาที่ผู้ใช้เห็นได้มาจาก User Permission ของ Service Branch ไม่มีเลย = เห็นทุกสาขา
  desk กรองเองจาก User Permission อยู่แล้ว ส่วนพอร์ทัล / Bay Monitor / รายงานที่ใช้ frappe.get_all
  หรือ SQL ตรง ต้องกรองด้วย branch_filters() / get_allowed_branches() เอง
"""

import frappe
from frappe.utils import cint

BRANCH_DOCTYPE = "Service Branch"

# ฟิลด์ที่สาขาตั้งทับค่ากลางได้ — ชื่อฟิลด์ตรงกันทั้งใน Service Branch และ Truck Service Center Settings
BRANCH_OVERRIDE_FIELDS = (
	"default_source_warehouse",
	"default_warehouse",
	"default_cost_center",
	"labor_cost_center",
	"sales_invoice_series",
	"work_day_monday",
	"work_day_tuesday",
	"work_day_wednesday",
	"work_day_thursday",
	"work_day_friday",
	"work_day_saturday",
	"work_day_sunday",
)

# เอกสารที่มีฟิลด์ branch — ตั้งค่าเริ่มต้นให้ผ่าน doc_events (hooks.py)
BRANCH_DOCTYPES = (
	"Service Appointment",
	"Service Order",
	"Repair Quotation",
	"Parts Return",
	"Service Bay",
	"Bay Capacity Override",
)


def get_branch_settings(branch=None):
	"""Truck Service Center Settings ที่ทับด้วยค่าของสาขา — สาขาไม่ได้ตั้งช่องใด ใช้ค่ากลาง

	คืนสำเนา (ไม่ใช่ตัวที่ cache ไว้) ทุกครั้งที่มีค่าทับ จึงแก้ค่าบนผลลัพธ์ได้โดยไม่ไปเปื้อน cache
	ห้าม save() ผลลัพธ์นี้ — เป็นค่าผสมของสองเอกสาร
	"""
	settings = frappe.get_cached_doc("Truck Service Center Settings")
	branch_doc = get_branch_doc(branch)
	if not branch_doc:
		return settings

	overrides = {field: branch_doc.get(field) for field in BRANCH_OVERRIDE_FIELDS if branch_doc.get(field)}
	if not overrides:
		return settings

	merged = frappe.get_doc(settings.as_dict())
	merged.update(overrides)
	return merged


def get_branch_doc(branch):
	if not branch or not frappe.db.exists(BRANCH_DOCTYPE, branch):
		return None
	return frappe.get_cached_doc(BRANCH_DOCTYPE, branch)


def get_allowed_branches(user=None):
	"""สาขาที่ผู้ใช้เห็นได้ — None = ไม่จำกัด (ไม่มี User Permission ของสาขาเลย หรือเป็น Administrator)"""
	user = user or frappe.session.user
	if user == "Administrator":
		return None

	from frappe.permissions import get_user_permissions

	rows = get_user_permissions(user).get(BRANCH_DOCTYPE) or []
	branches = sorted({row.get("doc") for row in rows if row.get("doc")})
	return branches or None


def is_branch_allowed(branch, user=None):
	allowed = get_allowed_branches(user)
	return allowed is None or branch in allowed


def branch_filters(filters=None, fieldname="branch", user=None):
	"""เติมเงื่อนไขสาขาตามสิทธิ์ผู้ใช้ลง filters (dict) — ผู้ใช้ไม่ถูกจำกัดสาขาจะได้ filters เดิมกลับไป"""
	filters = dict(filters or {})
	allowed = get_allowed_branches(user)
	if allowed is not None:
		filters[fieldname] = ["in", allowed]
	return filters


def get_default_branch(user=None):
	"""สาขาเริ่มต้นของเอกสารใหม่

	ลำดับ: User Permission ที่ติ๊ก is_default → สาขาเดียวที่ผู้ใช้มีสิทธิ์ → สาขาเริ่มต้นใน Settings
	(เฉพาะเมื่อผู้ใช้มีสิทธิ์สาขานั้น) → ถ้าทั้งระบบเปิดใช้อยู่สาขาเดียว ใช้สาขานั้น
	"""
	user = user or frappe.session.user
	allowed = get_allowed_branches(user)

	if allowed:
		from frappe.permissions import get_user_permissions

		for row in get_user_permissions(user).get(BRANCH_DOCTYPE) or []:
			if cint(row.get("is_default")) and row.get("doc") in allowed:
				return row.get("doc")
		if len(allowed) == 1:
			return allowed[0]

	default = frappe.db.get_single_value("Truck Service Center Settings", "default_branch")
	if default and (allowed is None or default in allowed):
		return default

	active = frappe.get_all(BRANCH_DOCTYPE, filters={"is_active": 1}, pluck="name", limit=2)
	if len(active) == 1 and (allowed is None or active[0] in allowed):
		return active[0]

	return allowed[0] if allowed else None


def set_default_branch(doc, method=None):
	"""doc_events (before_insert / before_validate) — เติมสาขาให้เอกสารที่ยังไม่ระบุ

	ต้องเกิดก่อนตั้งชื่อเอกสาร เพราะเลขเอกสารใช้รหัสนำหน้าของสาขา (branch_prefix)
	"""
	if doc.get("branch"):
		return

	branch = None
	if doc.doctype == "Bay Capacity Override" and doc.get("service_bay"):
		branch = frappe.db.get_value("Service Bay", doc.service_bay, "branch")
	elif doc.doctype == "Parts Return" and doc.get("service_order"):
		branch = frappe.db.get_value("Service Order", doc.service_order, "branch")

	doc.branch = branch or get_default_branch()


def validate_branch(doc, method=None):
	"""doc_events (validate) — สาขาต้องเปิดใช้งาน (เฉพาะตอนสร้างใหม่ เอกสารเก่าของสาขาที่ปิดไปแล้วยังแก้ได้)"""
	if not doc.get("branch"):
		return
	if doc.is_new() and not cint(frappe.db.get_value(BRANCH_DOCTYPE, doc.branch, "is_active")):
		frappe.throw(f"สาขา {doc.branch} ถูกปิดการใช้งานแล้ว")


def validate_bays_in_branch(branch, bays, label="ช่องจอด"):
	"""ช่องจอดทุกช่องที่เอกสารอ้างถึงต้องเป็นของสาขาเดียวกับเอกสาร — query เดียว"""
	bays = {bay for bay in bays if bay}
	if not branch or not bays:
		return

	wrong = [
		row.name
		for row in frappe.get_all(
			"Service Bay", filters={"name": ["in", list(bays)]}, fields=["name", "branch"]
		)
		if row.branch and row.branch != branch
	]
	if wrong:
		frappe.throw(f"{label} {', '.join(sorted(wrong))} ไม่ได้อยู่ในสาขา {branch}")


def branch_prefix(doc, part=None):
	"""naming_series_variables (hooks.py) — ".branch_prefix." ในชุดเลขเอกสาร

	สาขาที่ตั้ง document_prefix ได้ "BKK-" (SO-BKK-2026-00001) ไม่ตั้ง = ว่าง ซึ่งให้ชื่อและตัวนับ
	เดียวกับชุดเลขเดิม (SO-2026-00001) เลขของข้อมูลเดิมจึงรันต่อได้ไม่สะดุด
	"""
	branch = doc.get("branch") if doc else None
	if not branch:
		return ""
	prefix = (frappe.db.get_value(BRANCH_DOCTYPE, branch, "document_prefix") or "").strip()
	return f"{prefix}-" if prefix else ""


def get_last_service_branches(vehicles):
	"""{รถ: สาขาที่เข้าซ่อมล่าสุด} — query เดียว ใช้ส่งแจ้งเตือนรถถึงรอบให้สาขาที่ดูแลรถคันนั้น"""
	if not vehicles:
		return {}

	rows = frappe.get_all(
		"Service Order",
		filters={"vehicle": ["in", list(vehicles)], "docstatus": ["!=", 2], "branch": ["is", "set"]},
		fields=["vehicle", "branch"],
		order_by="service_date desc, creation desc",
	)
	result = {}
	for row in rows:
		result.setdefault(row.vehicle, row.branch)
	return result


def filter_users_by_branch(users, branch):
	"""ตัดผู้ใช้ที่ถูกผูกกับสาขาอื่นออก (ไม่ได้ผูกสาขาเลย = ทำงานได้ทุกสาขา) — query เดียว

	ใช้กับ dropdown ช่างของพอร์ทัล จะได้ไม่ assign ช่างสาขา A ให้งานของสาขา B
	"""
	users = list(users or [])
	if not branch or not users:
		return users

	branches_by_user = {}
	for row in frappe.get_all(
		"User Permission",
		filters={"allow": BRANCH_DOCTYPE, "user": ["in", users]},
		fields=["user", "for_value"],
	):
		branches_by_user.setdefault(row.user, set()).add(row.for_value)

	return [user for user in users if user not in branches_by_user or branch in branches_by_user[user]]


def branch_sql_condition(filters, alias="so", restrict=True):
	"""เงื่อนไข SQL ของสาขาสำหรับรายงาน (frappe.db.sql ไม่กรองตาม User Permission ให้เอง)

	filters.branch = สาขาที่เลือก (ต้องมีสิทธิ์) ไม่เลือก + ผู้ใช้ถูกผูกสาขา = เฉพาะสาขาของตัวเอง
	restrict=False สำหรับรายงานที่ตั้งใจให้เห็นข้ามสาขา (ประวัติซ่อมรถ — รถหนึ่งคันเข้าได้หลายสาขา)
	เติมค่าพารามิเตอร์ลง filters ให้เอง คืนสตริงที่ขึ้นต้นด้วย " and "
	"""
	branch = filters.get("branch")
	if branch:
		if restrict and not is_branch_allowed(branch):
			frappe.throw(f"คุณไม่มีสิทธิ์ดูข้อมูลของสาขา {branch}", frappe.PermissionError)
		return f" and {alias}.branch = %(branch)s"

	allowed = get_allowed_branches() if restrict else None
	if allowed is None:
		return ""
	filters["allowed_branches"] = tuple(allowed)
	return f" and {alias}.branch in %(allowed_branches)s"

# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""ใบคืนอะไหล่ — คืนของที่เบิกมาแล้วไม่ได้ใช้ (คืนบางส่วนได้ เช่นเบิก 4 คืน 1)

หนึ่งใบคืนต่อหนึ่งใบเบิกต้นทาง จึงใช้ผู้อนุมัติชุดเดียวกับใบเบิกนั้น (can_approve_requisition)

ทำงานบนสมมติฐานที่ระบบบังคับไว้: สต๊อก submit ใบเบิกของใบสั่งงานได้ก็ต่อเมื่อใบงานถึง "รอส่งมอบรถ"
แล้วเท่านั้น (validate_requisition_approved) ระหว่างซ่อมของจึงยังไม่ออกจากคลังทางบัญชี การคืนก็คือ
ลดจำนวนในใบเบิก Draft กับในใบสั่งงานลงพร้อมกัน — ไม่ต้องมี Material Receipt และจำนวนสองฝั่งยังตรงกัน
ตามที่ validate_material_issues_for_submit ต้องการ

ยอดเงินคืน = ราคาสุทธิต่อหน่วยของแถวอะไหล่ในใบสั่งงาน (rate - ส่วนลดต่อหน่วย) * จำนวนคืน
ส่วนลดของแถวอะไหล่เป็นต่อหน่วย ยอดของแถวที่เหลือจึงลดลงตรงกับยอดคืนพอดีเมื่อ calculate_totals คิดใหม่
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

RETURN_PENDING = "Pending"
RETURN_APPROVED = "Approved"
RETURN_REJECTED = "Rejected"

# ทศนิยมของจำนวน — ตรงกับ precision ของ Service Order Item.qty
QTY_PRECISION = 2


class PartsReturn(Document):
	def validate(self):
		for item in self.items:
			item.amount = flt(flt(item.rate) * flt(item.return_qty), 2)
		self.total_amount = flt(sum(flt(item.amount) for item in self.items), 2)


# ── pure ─────────────────────────────────────────────────────────────────────


def net_unit_rate(item):
	"""ราคาขายสุทธิต่อหน่วยของแถวอะไหล่ — สูตรเดียวกับ ServiceOrder._calculate_line_discount"""
	return max(flt(flt(item.get("rate")) - flt(item.get("discount_amount")), 2), 0.0)


def validate_return_lines(requested, available):
	"""ตรวจจำนวนที่ขอคืนเทียบกับที่คืนได้ → [(แถวอะไหล่, จำนวนคืน)] เรียงตามที่ส่งมา

	requested = {ชื่อแถว Service Order Item: จำนวน} (จำนวน 0 = ไม่คืนแถวนั้น ข้ามไป)
	available = {ชื่อแถว: _dict(max_qty, label)} จาก get_return_availability
	"""
	lines = []
	for row_name, qty in requested.items():
		qty = flt(qty, QTY_PRECISION)
		if qty == 0:
			continue
		info = available.get(row_name)
		if not info:
			frappe.throw(_("รายการที่เลือกไม่อยู่ในใบเบิกนี้ หรือคืนไม่ได้แล้ว — กรุณารีเฟรชหน้า"))
		if qty < 0:
			frappe.throw(_("จำนวนคืนของ {0} ต้องมากกว่า 0").format(info.label))
		if qty > flt(info.max_qty, QTY_PRECISION):
			frappe.throw(_("{0} คืนได้ไม่เกิน {1} (หักจำนวนที่รออนุมัติคืนอยู่แล้ว)").format(info.label, info.max_qty))
		lines.append((row_name, qty))

	if not lines:
		frappe.throw(_("กรุณาระบุจำนวนคืนอย่างน้อยหนึ่งรายการ"))
	return lines


# ── IO ───────────────────────────────────────────────────────────────────────


def get_pending_return_qty(stock_entries):
	"""จำนวนที่รออนุมัติคืนอยู่ ต่อแถวอะไหล่ → {ชื่อแถว Service Order Item: จำนวน} — 2 query"""
	names = frappe.get_all(
		"Parts Return",
		filters={"stock_entry": ["in", list(stock_entries)], "approval_status": RETURN_PENDING},
		pluck="name",
	)
	if not names:
		return {}

	pending = {}
	for row in frappe.get_all(
		"Parts Return Item",
		filters={"parent": ["in", names], "parenttype": "Parts Return"},
		fields=["service_order_item", "return_qty"],
	):
		pending[row.service_order_item] = flt(pending.get(row.service_order_item)) + flt(row.return_qty)
	return pending


def get_return_availability(service_order, stock_entries):
	"""แถวอะไหล่ที่คืนได้ของใบเบิกแต่ละใบ → {ใบเบิก: {ชื่อแถว: _dict(max_qty, issued_qty, ...)}}

	คืนได้เฉพาะใบเบิกที่ยังเป็น Draft และอนุมัติแล้ว (หรือใบเก่าไม่มีสถานะ) — ใบรออนุมัติให้ไม่อนุมัติ
	แล้วขอใหม่แทน ใบที่ submit แล้วของออกจากคลังไปแล้ว ต้องทำรับคืนที่ desk
	จำนวนตั้งต้นคือจำนวนในบรรทัดใบเบิก (สิ่งที่จะออกจากคลังจริง) หักที่รออนุมัติคืนอยู่ — 3-4 query
	"""
	stock_entries = [name for name in stock_entries if name]
	if not stock_entries:
		return {}

	entries = [
		row.name
		for row in frappe.get_all(
			"Stock Entry",
			filters={
				"name": ["in", stock_entries],
				"custom_service_order": service_order.name,
				"docstatus": 0,
			},
			fields=["name", "custom_approval_status"],
		)
		# กรองใน python — สถานะว่างมีทั้ง "" และ NULL ซึ่ง filter "in" จับ NULL ไม่ได้
		if (row.custom_approval_status or "") in ("Approved", "")
	]
	if not entries:
		return {}

	lines = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ["in", entries], "custom_service_order_item": ["is", "set"]},
		fields=["parent", "custom_service_order_item", "qty"],
	)
	pending = get_pending_return_qty(entries)
	rows = {row.name: row for row in service_order.service_items}

	availability = {}
	for line in lines:
		row = rows.get(line.custom_service_order_item)
		if not row or row.material_issue != line.parent:
			continue
		max_qty = flt(flt(line.qty) - flt(pending.get(row.name)), QTY_PRECISION)
		availability.setdefault(line.parent, {})[row.name] = frappe._dict(
			label=row.item_name or row.item_code,
			item_code=row.item_code,
			uom=row.uom or "",
			issued_qty=flt(line.qty),
			pending_qty=flt(pending.get(row.name)),
			max_qty=max(max_qty, 0.0),
			net_rate=net_unit_rate(row),
		)
	return availability


def create_parts_return(service_order, stock_entry, requested, reason=None, user=None):
	"""สร้างใบคืนสถานะรออนุมัติ — ผู้เรียกต้องตรวจสิทธิ์มาก่อนแล้ว"""
	from truck_service_center.truck_service_center.doctype.service_order.service_order import (
		get_user_display_name,
	)

	user = user or frappe.session.user
	available = get_return_availability(service_order, [stock_entry.name]).get(stock_entry.name) or {}
	if not available:
		frappe.throw(_("ใบเบิก {0} คืนอะไหล่ไม่ได้ (ยังไม่อนุมัติ, submit แล้ว หรือไม่มีรายการ)").format(stock_entry.name))

	lines = validate_return_lines(requested, available)

	doc = frappe.new_doc("Parts Return")
	doc.update(
		{
			"service_order": service_order.name,
			"branch": service_order.branch,
			"stock_entry": stock_entry.name,
			"service_type_group": stock_entry.get("custom_service_type_group"),
			"approval_status": RETURN_PENDING,
			"requested_by": user,
			"requested_by_name": get_user_display_name(user),
			"reason": (reason or "").strip() or None,
		}
	)
	for row_name, qty in lines:
		info = available[row_name]
		doc.append(
			"items",
			{
				"service_order_item": row_name,
				"item_code": info.item_code,
				"item_name": info.label,
				"uom": info.uom or None,
				"issued_qty": info.issued_qty,
				"return_qty": qty,
				"rate": info.net_rate,
			},
		)
	# ช่างไม่มีสิทธิ์สร้างเอกสารนี้บน desk — ด่านจริงอยู่ที่ endpoint ของพอร์ทัล
	doc.insert(ignore_permissions=True)
	return doc


def apply_parts_return(parts_return):
	"""อนุมัติใบคืน: ลดจำนวนในใบเบิก Draft และในใบสั่งงานลงเท่ากัน แล้วอัปเดตยอดเงินคืนของใบสั่งงาน

	บรรทัด/แถวที่เหลือ 0 ถูกลบทิ้ง (ERPNext ไม่ยอมให้บรรทัดจำนวน 0 และแถวอะไหล่จำนวน 0 ไม่มีความหมาย)
	ประวัติอยู่ในใบคืนนี้ ถ้าใบเบิกไม่เหลือรายการเลยจะถูกลบ (force — ใบคืนนี้ link ถึงอยู่)
	ราคาสุทธิคิดใหม่จากใบสั่งงาน ณ ตอนอนุมัติ เผื่อ desk แก้ราคาหลังช่างขอคืน
	"""
	service_order = frappe.get_doc("Service Order", parts_return.service_order, for_update=True)

	if not frappe.db.exists("Stock Entry", parts_return.stock_entry):
		frappe.throw(_("ใบเบิกต้นทาง {0} ถูกลบไปแล้ว — ไม่อนุมัติใบคืนนี้แทน").format(parts_return.stock_entry))
	stock_entry = frappe.get_doc("Stock Entry", parts_return.stock_entry, for_update=True)
	if stock_entry.docstatus != 0:
		frappe.throw(
			_("ใบเบิก {0} ถูก submit หรือยกเลิกแล้ว — คืนด้วยใบคืนนี้ไม่ได้ ต้องทำรับคืนที่สต๊อก").format(stock_entry.name)
		)

	rows = {row.name: row for row in service_order.service_items}
	lines = {line.get("custom_service_order_item"): line for line in stock_entry.items}

	for item in parts_return.items:
		row = rows.get(item.service_order_item)
		line = lines.get(item.service_order_item)
		if not row or not line or row.material_issue != stock_entry.name:
			frappe.throw(
				_("{0} ไม่อยู่ในใบเบิก {1} แล้ว — ไม่อนุมัติใบคืนนี้แทน").format(item.item_name, stock_entry.name)
			)

		qty = flt(item.return_qty, QTY_PRECISION)
		if qty > flt(line.qty, QTY_PRECISION):
			frappe.throw(_("{0} ในใบเบิกเหลือ {1} คืน {2} ไม่ได้").format(item.item_name, flt(line.qty), qty))

		item.rate = net_unit_rate(row)
		line.qty = flt(flt(line.qty) - qty, QTY_PRECISION)
		row.qty = max(flt(flt(row.qty) - qty, QTY_PRECISION), 0.0)
		row.returned_qty = flt(flt(row.get("returned_qty")) + qty, QTY_PRECISION)

	stock_entry.items = [line for line in stock_entry.items if flt(line.qty) > 0]
	if stock_entry.items:
		for idx, line in enumerate(stock_entry.items, start=1):
			line.idx = idx
		stock_entry.save(ignore_permissions=True)
	else:
		frappe.delete_doc("Stock Entry", stock_entry.name, ignore_permissions=True, force=True)
		parts_return.source_issue_removed = 1
		# stock_entry ยังเก็บชื่อใบที่ถูกลบไว้เป็นหลักฐาน — ข้ามการตรวจ link ตอนบันทึกครั้งนี้
		parts_return.flags.ignore_links = True
		# แถวที่ยังชี้ใบที่ถูกลบ (ถ้ามี) ต้องปลด link ไม่งั้นจะ submit ใบงานไม่ได้
		for row in service_order.service_items:
			if row.material_issue == stock_entry.name and flt(row.qty) > 0:
				row.material_issue = None
				row.material_issue_status = None

	service_order.service_items = [row for row in service_order.service_items if flt(row.qty) > 0]
	for idx, row in enumerate(service_order.service_items, start=1):
		row.idx = idx

	parts_return.approval_status = RETURN_APPROVED
	parts_return.save(ignore_permissions=True)

	service_order.returned_parts_amount = get_returned_amount(service_order.name)
	# ผู้อนุมัติ (หัวหน้างานกลุ่ม) อาจไม่มีสิทธิ์ write ใบสั่งงาน — ด่านจริงคือ can_approve_requisition
	service_order.save(ignore_permissions=True)
	return service_order


def get_returned_amount(service_order):
	"""ยอดเงินค่าอะไหล่ที่คืนแล้วทั้งหมดของใบสั่งงาน (เฉพาะใบคืนที่อนุมัติแล้ว)"""
	return flt(
		sum(
			frappe.get_all(
				"Parts Return",
				filters={"service_order": service_order, "approval_status": RETURN_APPROVED},
				pluck="total_amount",
			)
		),
		2,
	)


def stamp_return_decision(parts_return, status, reason=None, user=None):
	"""ประทับผู้พิจารณาลงใบคืน (ยังไม่บันทึก) — คู่กับ stamp_requisition_decision ของใบเบิก"""
	from truck_service_center.truck_service_center.doctype.service_order.service_order import (
		get_user_display_name,
	)

	user = user or frappe.session.user
	parts_return.update(
		{
			"approval_status": status,
			"approved_by": user,
			"approved_by_name": get_user_display_name(user),
			"approved_on": now_datetime(),
			"rejection_reason": reason if status == RETURN_REJECTED else None,
		}
	)

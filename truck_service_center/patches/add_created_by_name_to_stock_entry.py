# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from truck_service_center.install import CUSTOM_FIELDS
from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	get_user_display_name,
)

# ฟิลด์รอบก่อนที่เก็บ "ผู้เปิดใบสั่งงาน" — เข้าใจโจทย์ผิด ที่ต้องการคือผู้สร้างใบเบิก
SUPERSEDED_FIELD = "Stock Entry-custom_service_order_owner"


def execute():
	"""เพิ่มคอลัมน์ผู้สร้างใบเบิกบนหน้ารายการ Stock Entry แล้วเติมข้อมูลย้อนหลัง

	"ผู้สร้าง" คือ owner ของ Stock Entry (ช่างที่กดปุ่มในพอร์ทัล) ไม่ใช่ modified_by
	ซึ่งเป็นคน submit และมักเป็นผู้จัดการคนเดียวกันหมดทั้งระบบ

	ค่าถูกเขียนตอนสร้างใบเบิก ใบเก่าจึงยังว่าง — เติมด้วย db.set_value เพราะใบที่ submit
	แล้วจะ save ไม่ได้ และ update_modified=False เพื่อไม่ให้ประวัติการแก้ไขเพี้ยน
	"""
	drop_superseded_field()
	create_custom_fields(CUSTOM_FIELDS)
	backfill_creator_names()


def drop_superseded_field():
	"""ลบฟิลด์รอบก่อนทิ้ง — ไม่มี site ไหนใช้ค่าจากมันจริง"""
	if frappe.db.exists("Custom Field", SUPERSEDED_FIELD):
		frappe.delete_doc("Custom Field", SUPERSEDED_FIELD, force=1, ignore_permissions=True)


def backfill_creator_names():
	rows = frappe.get_all(
		"Stock Entry",
		filters={
			"custom_service_order": ["is", "set"],
			"custom_created_by_name": ["in", ["", None]],
		},
		fields=["name", "owner"],
	)
	if not rows:
		print("✓ ไม่มีใบเบิกที่ต้องเติมผู้สร้าง")
		return

	# ดึงชื่อทีเดียวกัน N+1 — ช่างคนเดียวมักสร้างใบเบิกหลายใบ
	owners = {row.owner for row in rows if row.owner}
	names = {owner: get_user_display_name(owner) for owner in owners}

	filled = 0
	for row in rows:
		label = names.get(row.owner)
		if not label:
			continue
		frappe.db.set_value("Stock Entry", row.name, "custom_created_by_name", label, update_modified=False)
		filled += 1

	print(f"✓ เติมผู้สร้างใบเบิก {filled} ใบ")

# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from truck_service_center.install import CUSTOM_FIELDS
from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	get_service_order_owner_label,
)


def execute():
	"""เพิ่มคอลัมน์ผู้เปิดใบสั่งงานบนหน้ารายการ Stock Entry แล้วเติมข้อมูลย้อนหลัง

	ค่าถูกเขียนตอนสร้างใบเบิก ใบเก่าจึงยังว่าง — เติมด้วย db.set_value เพราะใบที่ submit
	แล้วจะ save ไม่ได้ และ update_modified=False เพื่อไม่ให้ประวัติการแก้ไขเพี้ยน
	"""
	create_custom_fields(CUSTOM_FIELDS)
	backfill_owner_labels()


def backfill_owner_labels():
	rows = frappe.get_all(
		"Stock Entry",
		filters={
			"custom_service_order": ["is", "set"],
			"custom_service_order_owner": ["in", ["", None]],
		},
		fields=["name", "custom_service_order"],
	)
	if not rows:
		print("✓ ไม่มีใบเบิกที่ต้องเติมผู้เปิดใบสั่งงาน")
		return

	# ดึงเจ้าของใบสั่งงานทีเดียวกัน N+1 — ใบเบิกหลายใบมักมาจากใบสั่งงานเดียวกัน
	owners = dict(
		frappe.get_all(
			"Service Order",
			filters={"name": ["in", list({row.custom_service_order for row in rows})]},
			fields=["name", "owner"],
			as_list=True,
		)
	)
	labels = {owner: get_service_order_owner_label(owner) for owner in set(owners.values()) if owner}

	filled = 0
	for row in rows:
		label = labels.get(owners.get(row.custom_service_order))
		if not label:
			continue
		frappe.db.set_value(
			"Stock Entry", row.name, "custom_service_order_owner", label, update_modified=False
		)
		filled += 1

	print(f"✓ เติมผู้เปิดใบสั่งงานในใบเบิก {filled} ใบ")

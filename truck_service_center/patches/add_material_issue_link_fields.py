# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

from collections import Counter

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from truck_service_center.install import CUSTOM_FIELDS


def execute():
	"""สร้างฟิลด์เชื่อมใบเบิกอะไหล่กับใบสั่งงาน แล้วเติมข้อมูลย้อนหลัง

	create_material_issue เคยเขียน custom_service_order / custom_service_order_item_idx
	ลง Stock Entry ทั้งที่ฟิลด์ไม่เคยถูกสร้าง ค่าจึงหายไปทุกครั้ง ใบเบิกเดิมจึงไม่มี
	link กลับใบงานและปุ่ม Sync จับคู่แถวไม่ได้

	เติมย้อนหลังจากฝั่งที่ข้อมูลยังอยู่ คือ Service Order Item.material_issue
	"""
	create_custom_fields(CUSTOM_FIELDS)
	backfill_links()


def backfill_links():
	rows = frappe.get_all(
		"Service Order Item",
		filters={"material_issue": ["is", "set"]},
		fields=["name", "parent", "item_code", "material_issue"],
	)
	if not rows:
		return

	# จัดกลุ่มแถวใบงานตามใบเบิกที่ผูกอยู่
	by_issue = {}
	for row in rows:
		by_issue.setdefault(row.material_issue, []).append(row)

	linked_parents = 0
	linked_rows = 0
	ambiguous = 0

	for material_issue, so_rows in by_issue.items():
		if not frappe.db.exists("Stock Entry", material_issue):
			continue

		# แถวทั้งหมดของใบเบิกหนึ่งใบมาจากใบงานเดียวกันเสมอ (create_material_issue สร้างทีละใบงาน)
		frappe.db.set_value(
			"Stock Entry", material_issue, "custom_service_order", so_rows[0].parent, update_modified=False
		)
		linked_parents += 1

		se_rows = frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": material_issue},
			fields=["name", "item_code"],
		)

		# จับคู่ด้วย item_code ได้เฉพาะเมื่อไม่กำกวม คือ item_code นั้นมีฝั่งละแถวเดียว
		so_counts = Counter(r.item_code for r in so_rows)
		se_counts = Counter(r.item_code for r in se_rows)

		for se_row in se_rows:
			if so_counts[se_row.item_code] != 1 or se_counts[se_row.item_code] != 1:
				ambiguous += 1
				continue

			so_row = next(r for r in so_rows if r.item_code == se_row.item_code)
			frappe.db.set_value(
				"Stock Entry Detail",
				se_row.name,
				"custom_service_order_item",
				so_row.name,
				update_modified=False,
			)
			linked_rows += 1

	print(
		f"✓ เชื่อมใบเบิกกลับใบสั่งงาน {linked_parents} ใบ, รายการอะไหล่ {linked_rows} แถว"
		+ (f" (ข้าม {ambiguous} แถวที่ item_code ซ้ำจนจับคู่ไม่ได้)" if ambiguous else "")
	)

# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from truck_service_center.install import CUSTOM_FIELDS


def execute():
	"""เพิ่มฟิลด์ประเภทบริการในใบเบิกอะไหล่ แล้วเติมข้อมูลย้อนหลัง

	ใบเบิกเดิมบอกได้แค่ว่าเป็นของใบสั่งงานไหน (custom_service_order) แต่ไม่รู้ว่า
	เบิกให้งาน (service type) อะไร — เติมย้อนหลังจาก Service Order Item.service_type
	ผ่าน custom_service_order_item ที่ผูกแถวไว้อยู่แล้ว (แถวที่ service_type ว่าง
	คืออะไหล่ที่เพิ่มเอง จะยังว่างต่อไปตามความหมายเดิม)
	"""
	create_custom_fields(CUSTOM_FIELDS)
	backfill_service_types()


def backfill_service_types():
	se_rows = frappe.get_all(
		"Stock Entry Detail",
		filters={"custom_service_order_item": ["is", "set"]},
		fields=["name", "parent", "custom_service_order_item"],
	)
	if not se_rows:
		return

	so_item_types = dict(
		frappe.get_all(
			"Service Order Item",
			filters={
				"name": ["in", [r.custom_service_order_item for r in se_rows]],
				"service_type": ["is", "set"],
			},
			fields=["name", "service_type"],
			as_list=True,
		)
	)

	types_by_parent = {}
	linked_rows = 0
	for row in se_rows:
		service_type = so_item_types.get(row.custom_service_order_item)
		types_by_parent.setdefault(row.parent, set())
		if not service_type:
			continue
		frappe.db.set_value(
			"Stock Entry Detail", row.name, "custom_service_type", service_type, update_modified=False
		)
		types_by_parent[row.parent].add(service_type)
		linked_rows += 1

	# หัวใบระบุได้เฉพาะใบที่ทุกแถว(ที่รู้ที่มา)เป็นงานเดียวกัน — คละงานให้ดูรายบรรทัด
	linked_parents = 0
	for parent, service_types in types_by_parent.items():
		if len(service_types) == 1:
			frappe.db.set_value(
				"Stock Entry", parent, "custom_service_type", next(iter(service_types)), update_modified=False
			)
			linked_parents += 1

	print(f"✓ เติมประเภทบริการในใบเบิก {linked_parents} ใบ, รายการอะไหล่ {linked_rows} แถว")

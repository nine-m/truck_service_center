# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe

# คอลัมน์ที่ต้องมีบนหน้ารายการ Stock Entry เรียงตามลำดับที่อยากให้แทรก
WANTED_COLUMNS = [
	("custom_service_order", "ใบสั่งงาน"),
	("custom_service_order_owner", "ผู้เปิดใบสั่งงาน"),
]

# แทรกต่อจากคอลัมน์นี้ — ประเภทใบเบิกมาก่อน แล้วค่อยบอกว่าเป็นของใบสั่งงานไหน
ANCHOR_FIELD = "stock_entry_type"


def execute():
	"""ดันคอลัมน์ใบสั่งงาน/ผู้เปิดใบสั่งงานเข้า layout ที่ผู้ใช้ pin ไว้

	in_list_view บน Custom Field จะไม่มีผลเลยถ้า site นั้นมี List View Settings ของ
	doctype นั้นอยู่ — setup_columns ฝั่ง client จะใช้ list_view_settings.fields แทน
	docfield ทั้งหมด (frappe/public/js/frappe/list/list_view.js) record นั้นเกิดเองตั้งแต่
	มีคนลากปรับความกว้างคอลัมน์ ผู้ใช้จึงไม่รู้ตัวว่ามี layout ค้างอยู่

	เติมเฉพาะคอลัมน์ที่ขาด ไม่แตะลำดับหรือความกว้างของคอลัมน์อื่นที่ผู้ใช้ตั้งไว้
	ถ้า site ไหนยังไม่มี record นี้ก็ไม่ต้องทำอะไร — in_list_view ทำงานเองอยู่แล้ว
	"""
	if not frappe.db.exists("List View Settings", "Stock Entry"):
		print("✓ Stock Entry ยังไม่มี layout ที่ pin ไว้ — in_list_view แสดงคอลัมน์ให้เอง")
		return

	doc = frappe.get_doc("List View Settings", "Stock Entry")
	fields = frappe.parse_json(doc.fields) or []
	existing = {row.get("fieldname") for row in fields}

	missing = [
		{"fieldname": fieldname, "label": label}
		for fieldname, label in WANTED_COLUMNS
		if fieldname not in existing
	]
	if not missing:
		print("✓ layout ของ Stock Entry มีคอลัมน์ครบแล้ว")
		return

	anchor = next((i for i, row in enumerate(fields) if row.get("fieldname") == ANCHOR_FIELD), None)
	# ไม่เจอหลักยึดก็ต่อท้าย ดีกว่าเดาตำแหน่งแล้วสลับ layout ของผู้ใช้
	at = len(fields) if anchor is None else anchor + 1
	fields[at:at] = missing

	doc.fields = frappe.as_json(fields)
	doc.save(ignore_permissions=True)
	frappe.clear_cache(doctype="Stock Entry")

	print(f"✓ เพิ่มคอลัมน์ในหน้ารายการ Stock Entry: {', '.join(row['label'] for row in missing)}")

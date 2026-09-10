# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe

# คอลัมน์ที่ต้องมีบนหน้ารายการ Stock Entry เรียงตามลำดับที่อยากให้แสดง
WANTED_COLUMNS = [
	("custom_service_order", "ใบสั่งงาน"),
	("custom_created_by_name", "ผู้สร้างใบเบิก"),
]

# คอลัมน์รอบก่อนที่ถูกแทนที่ — ฟิลด์ถูกลบไปแล้ว ถ้าค้างใน layout จะได้ช่องว่าง
STALE_COLUMNS = {"custom_service_order_owner"}

# วางต่อจากคอลัมน์นี้ — ประเภทใบเบิกมาก่อน แล้วค่อยบอกว่าเป็นของใบสั่งงานไหน ใครสร้าง
ANCHOR_FIELD = "stock_entry_type"


def execute():
	"""ดันคอลัมน์ใบสั่งงาน/ผู้สร้างใบเบิกเข้า layout ที่ผู้ใช้ pin ไว้

	in_list_view บน Custom Field จะไม่มีผลเลยถ้า site นั้นมี List View Settings ของ
	doctype นั้นอยู่ — setup_columns ฝั่ง client จะใช้ list_view_settings.fields แทน
	docfield ทั้งหมด (frappe/public/js/frappe/list/list_view.js) record นั้นเกิดเองตั้งแต่
	มีคนลากปรับความกว้างคอลัมน์ ผู้ใช้จึงไม่รู้ตัวว่ามี layout ค้างอยู่

	แตะเฉพาะคอลัมน์ของแอปเอง — ดึงออกมาแล้ววางกลับเป็นก้อนเดียวต่อจากหลักยึด เพื่อให้
	ลำดับตรงกับ WANTED_COLUMNS เสมอ (ไม่งั้นการเพิ่มคอลัมน์ทีหลังจะไปแทรกสลับกับของเดิม)
	ความกว้างที่ผู้ใช้ลากไว้ถูกยกมาด้วย ส่วนคอลัมน์อื่นไม่ถูกจัดลำดับใหม่
	ถ้า site ไหนยังไม่มี record นี้ก็ไม่ต้องทำอะไร — in_list_view ทำงานเองอยู่แล้ว
	"""
	if not frappe.db.exists("List View Settings", "Stock Entry"):
		print("✓ Stock Entry ยังไม่มี layout ที่ pin ไว้ — in_list_view แสดงคอลัมน์ให้เอง")
		return

	doc = frappe.get_doc("List View Settings", "Stock Entry")
	before = frappe.parse_json(doc.fields) or []

	ours = {fieldname for fieldname, _ in WANTED_COLUMNS} | STALE_COLUMNS
	# เก็บของเดิมไว้เพื่อคง width ที่ผู้ใช้ลากไว้ (คอลัมน์ที่เลิกใช้ไม่ต้องเก็บ)
	kept = {row.get("fieldname"): row for row in before if row.get("fieldname") in ours}
	rest = [row for row in before if row.get("fieldname") not in ours]

	block = [
		kept.get(fieldname) or {"fieldname": fieldname, "label": label} for fieldname, label in WANTED_COLUMNS
	]

	anchor = next((i for i, row in enumerate(rest) if row.get("fieldname") == ANCHOR_FIELD), None)
	# ไม่เจอหลักยึดก็ต่อท้าย ดีกว่าเดาตำแหน่งแล้วสลับ layout ของผู้ใช้
	at = len(rest) if anchor is None else anchor + 1
	after = rest[:at] + block + rest[at:]

	if after == before:
		print("✓ layout ของ Stock Entry เรียงคอลัมน์ถูกอยู่แล้ว")
		return

	doc.fields = frappe.as_json(after)
	doc.save(ignore_permissions=True)
	frappe.clear_cache(doctype="Stock Entry")

	print(f"✓ จัดคอลัมน์หน้ารายการ Stock Entry: {', '.join(row['fieldname'] for row in after)}")

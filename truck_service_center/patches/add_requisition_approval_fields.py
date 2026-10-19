# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from truck_service_center.install import CUSTOM_FIELDS
from truck_service_center.patches import show_service_order_columns_in_stock_entry_list


def execute():
	"""เพิ่มฟิลด์ขั้นอนุมัติใบเบิกบน Stock Entry และเปลี่ยน label ผู้สร้างใบเบิก → ผู้ขอเบิก

	after_install ไม่รันซ้ำบน site เดิม — create_custom_fields (update=True) สร้างฟิลด์ใหม่และ
	ปรับ label ของฟิลด์เดิมให้ตรงกับ CUSTOM_FIELDS แล้วเติมคอลัมน์ใหม่เข้า layout ที่ผู้ใช้ pin ไว้
	ด้วยตัวเดียวกับ patch รอบก่อน (in_list_view ไม่มีผลถ้า site มี List View Settings)

	ใบเบิกเก่าไม่ต้อง backfill — สถานะอนุมัติว่างถือว่าผ่าน (validate_requisition_approved)
	"""
	create_custom_fields(CUSTOM_FIELDS)
	show_service_order_columns_in_stock_entry_list.execute()

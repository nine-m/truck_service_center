# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from truck_service_center.install import CUSTOM_FIELDS


def execute():
	"""เปิดช่องกรองด้วยเลขใบสั่งงานบนหน้ารายการ Stock Entry ของ site ที่ติดตั้งไปแล้ว

	ฟิลด์ custom_service_order มีอยู่แล้ว ขาดแค่ in_standard_filter จึงยังไม่มีช่อง
	ค้นหาบนหัวตาราง create_custom_fields(update=True เป็นค่าเริ่มต้น) อัปเดตฟิลด์เดิม
	ให้ตรงกับที่ประกาศไว้ใน CUSTOM_FIELDS โดยไม่แตะค่าที่ผู้ดูแลระบบตั้งไว้ที่อื่น
	"""
	create_custom_fields(CUSTOM_FIELDS)

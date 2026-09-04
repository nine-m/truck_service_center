# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe

DEFAULT_CAPACITY_HOURS = 8


def execute():
	"""เติมชั่วโมงรับงานต่อวันให้ช่องจอดที่ยังไม่มีค่า

	ฟิลด์ใหม่บนแถวเดิมจะเป็น NULL หรือ 0 ซึ่งระบบความจุจะอ่านว่า "เต็มถาวร"
	จึงต้องเติมค่าเริ่มต้นให้ก่อน — idempotent รันซ้ำได้ ไม่ทับค่าที่ตั้งไว้แล้ว

	อ่านด้วย SQL ตรง ๆ เพราะ filter ของ frappe.get_all กับค่า 0 จะไม่ครอบคลุม NULL
	"""
	bays = frappe.db.sql_list("select name from `tabService Bay` where ifnull(daily_capacity_hours, 0) = 0")
	for bay in bays:
		frappe.db.set_value(
			"Service Bay", bay, "daily_capacity_hours", DEFAULT_CAPACITY_HOURS, update_modified=False
		)

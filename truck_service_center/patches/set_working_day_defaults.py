# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""ตั้งค่าเริ่มต้นวันทำการใน Truck Service Center Settings

	ฟิลด์ใหม่บน Single doctype จะเป็น NULL บน site เดิม (default ใน JSON
	ไม่ถูกเขียนลง DB ให้เอง) — เติมเฉพาะค่าที่ยังไม่เคยตั้ง เพื่อไม่ทับ
	ค่าที่ผู้ใช้ปรับไว้แล้ว
	"""
	defaults = {
		"work_day_monday": "เต็มวัน",
		"work_day_tuesday": "เต็มวัน",
		"work_day_wednesday": "เต็มวัน",
		"work_day_thursday": "เต็มวัน",
		"work_day_friday": "เต็มวัน",
		"work_day_saturday": "ครึ่งวัน",
		"work_day_sunday": "หยุด",
	}

	for field, value in defaults.items():
		# ต้องอ่านดิบจากตาราง Singles — get_single_value จะคืนค่าว่างทั้งกรณี
		# "ยังไม่เคยตั้ง" และ "ตั้งเป็นค่าว่าง" ทำให้แยกกันไม่ออก
		raw = frappe.db.get_value(
			"Singles",
			{"doctype": "Truck Service Center Settings", "field": field},
			"value",
			order_by=None,
		)
		if raw is None:
			frappe.db.set_single_value("Truck Service Center Settings", field, value)

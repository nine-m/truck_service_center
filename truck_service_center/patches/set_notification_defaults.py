# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""ตั้งค่าเริ่มต้นการแจ้งเตือนใน Truck Service Center Settings

	ฟิลด์ใหม่บน Single doctype จะเป็น NULL บน site เดิม (default ใน JSON
	ไม่ถูกเขียนลง DB ให้เอง) — เติมเฉพาะค่าที่ยังไม่เคยตั้ง เพื่อไม่ทับ
	ค่าที่ผู้ใช้ปรับไว้แล้ว
	"""
	defaults = {
		"enable_expiry_notifications": 1,
		"expiry_notice_days": 30,
		"enable_service_due_notifications": 1,
		"service_due_notice_days": 7,
	}

	for field, value in defaults.items():
		# ต้องอ่านดิบจากตาราง Singles — get_single_value จะ cast NULL ของ Check/Int เป็น 0
		# ทำให้แยก "ยังไม่เคยตั้ง" กับ "ตั้งใจปิด" ไม่ออก
		raw = frappe.db.get_value(
			"Singles",
			{"doctype": "Truck Service Center Settings", "field": field},
			"value",
			order_by=None,
		)
		if raw is None:
			frappe.db.set_single_value("Truck Service Center Settings", field, value)

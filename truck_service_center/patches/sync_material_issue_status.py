# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

import frappe

from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	sync_material_issue_status,
)


def execute():
	"""เติมสถานะใบเบิกอะไหล่ที่ค้างอยู่ใน Service Order Item

	ก่อนมี doc_events บน Stock Entry ฟิลด์ material_issue_status ถูกอัปเดตเฉพาะตอน
	save ใบงาน แถวที่ใบเบิกถูก submit/cancel หลังจากนั้นจึงค้างค่าเก่าไว้ใน DB

	ใช้ฟังก์ชันตัวเดียวกับ hook เพื่อไม่ให้พฤติกรรมแตกเป็นสองทาง — หมายความว่า
	แถวที่ผูกกับใบเบิกที่ถูกยกเลิกไปแล้วจะโดนปลด link ตามกติกาใหม่ด้วย
	"""
	material_issues = frappe.get_all(
		"Service Order Item",
		filters={"material_issue": ["is", "set"]},
		pluck="material_issue",
		distinct=True,
	)

	for material_issue in material_issues:
		sync_material_issue_status(material_issue)

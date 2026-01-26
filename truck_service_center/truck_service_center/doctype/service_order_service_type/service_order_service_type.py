# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ServiceOrderServiceType(Document):
	pass


@frappe.whitelist()
def get_service_type_query(doctype, txt, searchfield, start, page_len, filters):
	"""Filter Service Type ตาม service_type_group ที่เลือก"""
	# ดึง service_type_group จาก filters
	service_type_group = None
	
	# ตรวจสอบว่า filters เป็น dict หรือไม่
	if isinstance(filters, dict):
		service_type_group = filters.get('service_type_group')
	elif isinstance(filters, str):
		# ถ้าเป็น string ให้ใช้เป็น service_type_group
		service_type_group = filters
	
	conditions = ["is_active = 1"]
	values = []
	
	# ถ้ามีการเลือก group ให้ filter ตาม group
	if service_type_group:
		conditions.append("service_type_group = %s")
		values.append(service_type_group)
	
	# เพิ่มเงื่อนไขการค้นหา
	if txt:
		conditions.append("service_type_name LIKE %s")
		values.append(f"%{txt}%")
	
	query = f"""
		SELECT name, service_type_name, maintenance_type, service_type_group
		FROM `tabService Type`
		WHERE {' AND '.join(conditions)}
		ORDER BY 
			CASE WHEN service_type_name LIKE %s THEN 0 ELSE 1 END,
			service_type_name
		LIMIT {start}, {page_len}
	"""
	
	# เพิ่ม txt สำหรับ ORDER BY
	if txt:
		values.append(f"{txt}%")
	else:
		values.append("")
	
	return frappe.db.sql(query, tuple(values))

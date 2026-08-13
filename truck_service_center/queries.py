# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

"""Link-field search queries ที่ใช้ร่วมกันหลาย doctype ของศูนย์บริการ"""

from typing import Any

import frappe

TECHNICIAN_ROLE = "Technician"

# ผู้ใช้ระบบมาตรฐานของ Frappe — ไม่ควรขึ้นในรายชื่อช่าง
EXCLUDED_USERS = ("Administrator", "Guest")


def get_technician_users() -> list[str]:
	"""Return ผู้ใช้ที่ถูกกำหนดบทบาท Technician (ไม่รวม user มาตรฐานของระบบ)"""
	users = frappe.get_all(
		"Has Role",
		filters={"role": TECHNICIAN_ROLE, "parenttype": "User"},
		pluck="parent",
	)
	return [user for user in users if user not in EXCLUDED_USERS]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def technician_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict[str, Any]
):
	"""ค้นหาช่างสำหรับฟิลด์ Link → User

	กรองเฉพาะผู้ใช้ที่มีบทบาท "Technician" เพื่อไม่ให้ dropdown ขึ้น user ทุกคนในระบบ
	ถ้ายังไม่มีใครได้รับบทบาทนี้เลย จะถอยไปแสดง system user ทั้งหมด — กัน dropdown ว่าง
	บนไซต์ที่ยังไม่ได้ตั้งบทบาทช่าง
	"""
	list_filters: dict[str, Any] = {
		"enabled": 1,
		"user_type": ("!=", "Website User"),
	}

	technicians = get_technician_users()
	if technicians:
		list_filters["name"] = ("in", technicians)
	else:
		list_filters["name"] = ("not in", EXCLUDED_USERS)

	if filters:
		list_filters.update(filters)

	or_filters = [[searchfield, "like", f"%{txt}%"]]
	if "name" in searchfield:
		or_filters += [[field, "like", f"%{txt}%"] for field in ("first_name", "last_name")]

	return frappe.get_list(
		"User",
		filters=list_filters,
		or_filters=or_filters,
		fields=["name", "full_name"],
		limit_start=start,
		limit_page_length=page_len,
		order_by="full_name asc",
		as_list=True,
	)

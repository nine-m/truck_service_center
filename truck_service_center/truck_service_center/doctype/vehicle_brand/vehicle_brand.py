# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class VehicleBrand(Document):
	pass


@frappe.whitelist()
def get_active_brands():
	"""ดึงรายการยี่ห้อรถที่เปิดใช้งาน"""
	return frappe.get_all(
		"Vehicle Brand",
		filters={"is_active": 1},
		fields=["name", "brand_name"],
		order_by="brand_name",
	)

# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe

# ยี่ห้อรถบรรทุก/รถเพื่อการพาณิชย์ที่จำหน่ายในประเทศไทย
DEFAULT_VEHICLE_BRANDS = [
	"Isuzu",
	"Hino",
	"Mitsubishi Fuso",
	"UD Trucks",
	"Toyota",
	"Foton",
	"Sinotruk",
	"Dongfeng",
	"FAW",
	"JAC",
	"Chenglong",
	"Maxus",
	"Tata",
	"Scania",
	"Volvo",
	"MAN",
	"Mercedes-Benz",
	"DAF",
]


def after_install():
	create_default_vehicle_brands()


def create_default_vehicle_brands():
	"""สร้างยี่ห้อรถเริ่มต้น (ยี่ห้อรถบรรทุกที่ขายในประเทศไทย)"""
	created = 0
	for brand_name in DEFAULT_VEHICLE_BRANDS:
		if frappe.db.exists("Vehicle Brand", brand_name):
			continue

		doc = frappe.get_doc(
			{
				"doctype": "Vehicle Brand",
				"brand_name": brand_name,
				"is_active": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		created += 1

	if created:
		frappe.db.commit()

	print(f"✓ สร้างยี่ห้อรถเริ่มต้นเรียบร้อย ({created} รายการ)")

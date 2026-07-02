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


# บทบาทผู้ใช้ของศูนย์บริการ (ดู permission matrix ใน DOCTYPES_README.md)
DEFAULT_ROLES = [
	"Service Manager",  # ผู้จัดการศูนย์ — สิทธิ์เต็มทุก doctype ของแอป
	"Service User",  # ธุรการ/Service Advisor — รับรถ นัดหมาย เสนอราคา เปิดใบสั่งงาน
	"Technician",  # ช่าง — ดูงานและอัพเดทงานซ่อม
]


def after_install():
	create_default_roles()
	create_default_vehicle_brands()


def create_default_roles():
	"""สร้างบทบาทผู้ใช้เริ่มต้นของศูนย์บริการ (idempotent)"""
	created = 0
	for role_name in DEFAULT_ROLES:
		if frappe.db.exists("Role", role_name):
			continue

		doc = frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		created += 1

	if created:
		frappe.db.commit()

	print(f"✓ สร้างบทบาทผู้ใช้เริ่มต้นเรียบร้อย ({created} รายการ)")


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

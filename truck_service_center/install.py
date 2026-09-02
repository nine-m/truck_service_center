# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# ฟิลด์ที่แอปเพิ่มบน doctype ของ ERPNext เพื่อเชื่อมใบเบิกอะไหล่กลับมายังใบสั่งงาน
# ทั้งคู่ระบบเป็นคนเขียน (create_material_issue) ผู้ใช้ไม่ต้องกรอกเอง
CUSTOM_FIELDS = {
	"Stock Entry": [
		{
			"fieldname": "custom_service_order",
			"label": "ใบสั่งงาน",
			"fieldtype": "Link",
			"options": "Service Order",
			"insert_after": "stock_entry_type",
			"read_only": 1,
			"no_copy": 1,  # amend ใบเบิกแล้วต้องไม่ลากใบงานเดิมติดไปด้วย
			"print_hide": 1,
		}
	],
	"Stock Entry Detail": [
		{
			"fieldname": "custom_service_order_item",
			# เก็บ name ของแถวใน Service Order Item — ใช้ Data ไม่ใช่ Link เพราะ Link
			# ไปหา child doctype ไม่มี UI รองรับ และจะไปพัวพันกับ link check ตอน cancel
			"label": "แถวอะไหล่ในใบสั่งงาน",
			"fieldtype": "Data",
			"insert_after": "expense_account",
			"read_only": 1,
			"no_copy": 1,
			"hidden": 1,
			"print_hide": 1,
		}
	],
}

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
	"Technician Manager",  # หัวหน้าช่าง — เห็นและอัพเดทงานได้ทุกใบในพอร์ทัลช่าง แม้ไม่ได้ถูก assign
]


# ชุด role สำเร็จรูปให้เลือกตอนสร้าง user (doctype Role Profile)
DEFAULT_ROLE_PROFILES = {
	"Technician": ["Technician"],
	# หัวหน้าช่างทำงานช่างด้วย จึงได้ Technician ติดไปด้วย ไม่ใช่แค่สิทธิ์ดูทุกใบ
	"Technician Manager": ["Technician", "Technician Manager"],
}


def after_install():
	create_custom_fields(CUSTOM_FIELDS)
	create_default_roles()
	create_default_role_profiles()
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


def create_default_role_profiles():
	"""สร้าง Role Profile สำเร็จรูปของศูนย์บริการ (idempotent)

	ถ้า profile มีอยู่แล้วจะเติมเฉพาะ role ที่ยังขาด ไม่ลบของที่ผู้ดูแลระบบเพิ่มเอง
	"""
	touched = 0
	for profile_name, roles in DEFAULT_ROLE_PROFILES.items():
		missing_roles = [role for role in roles if not frappe.db.exists("Role", role)]
		if missing_roles:
			print(f"⚠ ข้าม Role Profile {profile_name} เพราะยังไม่มี role: {', '.join(missing_roles)}")
			continue

		if frappe.db.exists("Role Profile", profile_name):
			doc = frappe.get_doc("Role Profile", profile_name)
			existing = {row.role for row in doc.roles}
			added = [role for role in roles if role not in existing]
			if not added:
				continue
			for role in added:
				doc.append("roles", {"role": role})
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.get_doc(
				{
					"doctype": "Role Profile",
					"role_profile": profile_name,
					"roles": [{"role": role} for role in roles],
				}
			)
			doc.insert(ignore_permissions=True)

		touched += 1

	if touched:
		frappe.db.commit()

	print(f"✓ สร้าง/อัปเดต Role Profile เรียบร้อย ({touched} รายการ)")


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

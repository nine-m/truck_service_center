# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

from truck_service_center.install import create_default_role_profiles


def execute():
	"""สร้าง Role Profile "Technician" / "Technician Manager" บน site ที่ติดตั้งไปแล้ว

	after_install ไม่ทำงานซ้ำบน site เดิม ต้องมา patch ให้
	ตัว seeder เป็น idempotent (เติมเฉพาะ role ที่ขาด) จึงเรียกซ้ำได้
	"""
	create_default_role_profiles()

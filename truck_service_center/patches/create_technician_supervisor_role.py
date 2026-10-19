# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

from truck_service_center.install import create_default_role_profiles, create_default_roles


def execute():
	"""สร้าง role + Role Profile "Technician Supervisor" บน site ที่ติดตั้งไปแล้ว

	รันใน pre_model_sync — สิทธิ์ของ Service Order อ้าง role นี้ จึงต้องมี role ก่อน doctype ถูก sync
	ทั้งสอง seeder เป็น idempotent (ข้ามของที่มีอยู่ / เติมเฉพาะ role ที่ขาด) จึงเรียกซ้ำได้ปลอดภัย
	"""
	create_default_roles()
	create_default_role_profiles()

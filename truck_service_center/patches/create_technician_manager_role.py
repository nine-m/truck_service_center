# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

from truck_service_center.install import create_default_roles


def execute():
	"""สร้าง role "Technician Manager" บน site ที่ติดตั้งไปแล้ว

	after_install ไม่ทำงานซ้ำบน site เดิม role ที่เพิ่มเข้า DEFAULT_ROLES ภายหลัง
	จึงต้องอาศัย patch ตัวนี้ create_default_roles เป็น idempotent อยู่แล้ว
	(ข้าม role ที่มีอยู่) จึงเรียกซ้ำได้ปลอดภัย
	"""
	create_default_roles()

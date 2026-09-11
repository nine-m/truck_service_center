# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

from truck_service_center.install import create_default_bay_types


def execute():
	"""seed ประเภทช่องจอดเริ่มต้นให้ site ที่ติดตั้งไปแล้ว

	after_install ไม่รันบน site เดิม และ migrate_pit_to_bay_type ที่ตามมาต้องมี
	GENERAL/PIT อยู่ก่อนถึงจะย้ายข้อมูลได้ patch นี้จึงต้องมาก่อนเสมอ
	"""
	create_default_bay_types()

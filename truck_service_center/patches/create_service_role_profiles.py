# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

from truck_service_center.install import create_default_role_profiles


def execute():
	"""สร้าง Role Profile "Service User" / "Service Manager" บน site ที่ติดตั้งไปแล้ว

	ก่อนหน้านี้มี profile สำเร็จรูปแค่ฝั่งช่าง ผู้ดูแลระบบที่สร้าง user ใหม่จึงไม่มีชุด
	role ให้เลือกสำหรับธุรการ/ผู้จัดการศูนย์ พอไม่ได้ติ๊ก role เองผู้ใช้ใหม่ก็ล็อกอินมา
	แล้วไม่เห็นหน้าหลักของศูนย์บริการ (frappe ตอบ "No App" แล้วส่งไป /me)

	create_default_role_profiles เป็น idempotent — profile เดิมจะถูกเติมเฉพาะ role
	ที่ยังขาด (เช่น Sales User ที่เพิ่งพ่วงเข้าไป) ไม่ลบของที่ผู้ดูแลระบบเพิ่มเอง
	"""
	create_default_role_profiles()

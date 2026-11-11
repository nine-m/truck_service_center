"""ลบ number card ชุดเดิมที่ซ้ำกับกราฟ/shortcut บน dashboard

migrate ไม่ลบ record มาตรฐานที่ไฟล์ถูกลบไปแล้ว จึงต้องลบเองครั้งเดียว
- งานซ่อมที่เสร็จแล้ว / งานซ่อมที่กำลังดำเนินการ — ซ้ำกับกราฟโดนัทสถานะงานซ่อม
- รายได้ (งานที่เสร็จแล้ว) — ซ้ำกับกราฟรายได้รายเดือน
- รถที่ใช้งานอยู่ — ซ้ำกับตัวเลขบน shortcut Vehicle
- นัดหมายที่กำลังจะมาถึง — แทนด้วย นัดหมายวันนี้ (ของเดิมนับนัดเก่าที่ไม่ถูกปิดสถานะด้วย)
"""

import frappe

REMOVED_CARDS = (
	"งานซ่อมที่กำลังดำเนินการ",
	"งานซ่อมที่เสร็จแล้ว",
	"นัดหมายที่กำลังจะมาถึง",
	"รายได้ (งานที่เสร็จแล้ว)",
	"รถที่ใช้งานอยู่",
)


def execute():
	for name in REMOVED_CARDS:
		# แถว Workspace Number Card ที่ยังชี้อยู่ (workspace ที่ผู้ใช้ copy ไว้เอง) ต้องหายไปด้วย
		# ไม่งั้น delete_doc ติด link และ workspace นั้นจะมีบล็อกที่หาการ์ดไม่เจอ
		frappe.db.delete("Workspace Number Card", {"number_card_name": name})
		frappe.delete_doc("Number Card", name, ignore_missing=True, force=True)

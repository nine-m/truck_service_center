import frappe

def create_repair_positions():
	"""สร้างข้อมูลตำแหน่งที่ซ่อมเริ่มต้น"""
	
	positions = [
		# ระบบไฟฟ้า (EL)
		{"position_code": "EL00", "position_name": "ระบบไฟฟ้า", "remark": ""},
		{"position_code": "EL01", "position_name": "ไฟตรงเซ็นไฟ", "remark": "ไฟตรงเซ็นไฟจากภายนอก"},
		{"position_code": "EL02", "position_name": "ไฟตรงเซ็นไฟจากเคลื่อน", "remark": "ไฟเลี้ยวซ้ายขวาและไฟถอยหลัง ตำแหน่งจากภายนอก"},
		
		# เครื่องยนต์ (EN)
		{"position_code": "EN00", "position_name": "เครื่องยนต์", "remark": ""},
		{"position_code": "EN01", "position_name": "มาติวจากเครื่องยนต์", "remark": "มาติวจากเครื่องยนต์เลื่อนเข้าออกหรือเป็นบล็อกและจากนอก ได้เบา"},
		
		# ช่วงล่าง (SU)
		{"position_code": "SU00", "position_name": "ช่วงล่าง", "remark": ""},
		{"position_code": "SU01", "position_name": "ใบยเนอเรทรองล่าง", "remark": "ช่องเบรกหน้ายางล่างจากข้า"},
		{"position_code": "SU02", "position_name": "ใบยเนอเรทรองล่างหลัง", "remark": "ช่องเบรกหน้ายางล่างจากหลัง"},
		
		# ยาง (TY)
		{"position_code": "TY00", "position_name": "ยาง", "remark": ""},
		{"position_code": "TY01", "position_name": "ขายตาของยางล่าง", "remark": "เปลี่ยนยางล่างจากข้า"},
		{"position_code": "TY02", "position_name": "ขายตาของยางล่างหลัง", "remark": "เปลี่ยนยางล่างจากข้าหลัง"},
		{"position_code": "TY03", "position_name": "สมิดซ์อฟต์", "remark": "สมิดซ์อฟต์ยางล่างจากข้าทั้งหมดให้"},
		{"position_code": "TY04", "position_name": "สมิดซ์อฟต์ (2)", "remark": "เปลี่ยนสมิดซ์อฟต์ยางล่างจากข้ายางเดียวหนึ่ง"},
		{"position_code": "TY05", "position_name": "สมิดซ์อฟต์ (3)", "remark": "เปลี่ยนสมิดซ์อฟต์ยางล่างจากข้าทั้งหมดของยางหลัง"},
		{"position_code": "TY06", "position_name": "สมิดซ์อฟต์ (4)", "remark": "เปลี่ยนสมิดซ์อฟต์ยางล่างจากข้ายางเดียวหลัง"},
		{"position_code": "TY07", "position_name": "สมิดซ์อฟต์ (5)", "remark": "เปลี่ยนสมิดซ์อฟต์ยางล่างจากข้าทั้งหมดให้"},
		{"position_code": "TY08", "position_name": "สมิดซ์อฟต์ (6)", "remark": "เปลี่ยนสมิดซ์อฟต์ยางล่างจากข้าทั้งหมดของยางหนึ่ง"},
		{"position_code": "TY09", "position_name": "สมิดซ์อฟต์ (7)", "remark": "เปลี่ยนสมิดซ์อฟต์ยางล่างจากข้าทั้งหมดของยางหลัง"},
		{"position_code": "TY10", "position_name": "สมิดซ์อฟต์ (8)", "remark": "เปลี่ยนสมิดซ์อฟต์ยางล่างจากข้ายางเดียวหลัง"},
		{"position_code": "TY11", "position_name": "ยางผางส่าก", "remark": ""},
		{"position_code": "TY12", "position_name": "ยางผางส่าก (2)", "remark": "เปลี่ยนยางผางส่าก หยอมส่าก หนึ่ง"},
		{"position_code": "TY13", "position_name": "ยางผางส่าก (3)", "remark": "เปลี่ยนยางผางส่าก หยอมส่าก ทั้งหมดหนึ่ง"},
		{"position_code": "TY14", "position_name": "ยางผางส่าก (4)", "remark": "เปลี่ยนยางผางส่าก หยอมส่าก หลัง"},
		{"position_code": "TY15", "position_name": "ยางผางส่าก (5)", "remark": "เปลี่ยนยางผางส่าก หยอมส่าก ทั้งหมดหลัง"},
		{"position_code": "TY16", "position_name": "ยางผางส่าก (6)", "remark": "เปลี่ยนยางผางส่าก หยอมส่าก ทั้งหมดให้"},
		{"position_code": "TY17", "position_name": "ยางผางส่าก (7)", "remark": "เปลี่ยนยางผางส่าก หยอมส่าก ทั้งหมดหนึ่ง"},
		{"position_code": "TY18", "position_name": "ยางผางส่าก (8)", "remark": "เปลี่ยนยางผางส่าก หยอมส่าก ทั้งหมดหลัง"},
		{"position_code": "TY19", "position_name": "สมิดซ์อฟต์ (9)", "remark": "เปลี่ยนสมิดซ์อฟต์ยางล่างจากข้ายางเดียวหนึ่ง"},
		{"position_code": "TY20", "position_name": "สมิดซ์อฟต์ (10)", "remark": "เปลี่ยนสมิดซ์อฟต์ยางล่างจากข้าทั้งหมดหนึ่ง"},
	]
	
	for pos in positions:
		if not frappe.db.exists("Repair Position", pos["position_code"]):
			doc = frappe.get_doc({
				"doctype": "Repair Position",
				"position_code": pos["position_code"],
				"position_name": pos["position_name"],
				"remark": pos["remark"],
				"is_active": 1
			})
			doc.insert()
			print(f"Created: {pos['position_code']} - {pos['position_name']}")
		else:
			print(f"Exists: {pos['position_code']}")
	
	frappe.db.commit()
	print("\nRepair Position data created successfully!")

if __name__ == "__main__":
	create_repair_positions()

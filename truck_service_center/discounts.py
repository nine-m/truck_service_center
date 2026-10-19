# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""ส่วนลดรายบรรทัด — จำนวนเงิน (บาท) เป็นตัวหลัก, % เป็นค่าที่คำนวณไว้แสดง

% ถูกเก็บแบบปัด 2 ตำแหน่ง ถ้าคิดบาทกลับจาก % ทุกครั้งจะได้เศษ
(ค่าแรง 300 ลด 100 บาท → 33.33% → 300 x 33.33% = 99.99 → ยอด 200.01)

ฝั่ง client มี mirror ของ resolve_line_discount อยู่ใน service_order.js และ repair_quotation.js
(ต้องแก้คู่กัน) ส่วน Service Package ใช้กติกาเดียวกันกับคู่ package_rate / discount_percent
"""

from frappe.utils import flt


def percent_of(amount, base):
	"""amount คิดเป็นกี่ % ของ base (ปัด 2 ตำแหน่ง) — base ไม่เป็นบวกคืน 0"""
	base = flt(base)
	if base <= 0:
		return 0
	return flt(flt(amount) / base * 100, 2)


def resolve_line_discount(base, discount_percentage, discount_amount):
	"""คืน (discount_percentage, discount_amount) ที่สอดคล้องกัน

	คิดบาทจาก % เฉพาะเมื่อ % ไม่ตรงกับบาทที่มีอยู่ ซึ่งแปลว่าผู้ใช้เพิ่งแก้ % (หรือราคาฐานเปลี่ยน
	ซึ่งคง % ไว้เหมือนพฤติกรรมเดิม) — ถ้าตรงกันอยู่แล้วบาทคือค่าที่ผู้ใช้คีย์ จึงเก็บไว้ตามนั้น
	% ที่คืนเป็นค่าที่คำนวณจากบาทเสมอ
	"""
	base = flt(base)
	pct = flt(discount_percentage)
	amount = flt(discount_amount, 2)

	if base <= 0:
		return pct, amount

	if pct and percent_of(amount, base) != flt(pct, 2):
		amount = flt(base * pct / 100, 2)

	return percent_of(amount, base), amount


def distribute_package_discount(package):
	"""แจกส่วนลดของแพ็คเกจเป็นบาทลงแต่ละบรรทัด ให้ยอดรวมหลังส่วนลดตรงราคาแพ็คเกจพอดี

	เดิมใส่ % ของแพ็คเกจลงทุกแถว แต่ละแถวปัดเศษแยกกัน ผลรวมจึงคลาดได้
	(แพ็คเกจ 7,250 ขาย 5,000 → 31.03% → แถวรวมกันได้ 4,999.99)
	เศษจากการปัดไปลงที่แถวค่าแรงที่ใหญ่ที่สุด (จำนวน 1 เสมอ) ถ้าไม่มีค่าแรงจะลงแถวอะไหล่
	จำนวน 1 ที่ราคาสูงสุด — ส่วนลดอะไหล่เป็นต่อหน่วย แถวที่จำนวนมากกว่า 1 จึงรับเศษไม่ได้

	คืน (ส่วนลดต่อแถวค่าแรง, ส่วนลดต่อหน่วยของแถวอะไหล่) เรียงตาม package_service_types / package_parts
	"""
	labor_rates = [flt(row.labor_rate) for row in package.package_service_types]
	parts = [(flt(row.rate), flt(row.qty)) for row in package.package_parts]

	standard = sum(labor_rates) + sum(rate * qty for rate, qty in parts)
	total_discount = flt(standard - flt(package.package_rate), 2) if flt(package.package_rate) else 0
	if standard <= 0 or total_discount <= 0:
		return [0] * len(labor_rates), [0] * len(parts)

	ratio = total_discount / standard
	labor = [flt(rate * ratio, 2) for rate in labor_rates]
	unit = [flt(rate * ratio, 2) for rate, _ in parts]

	remainder = flt(
		total_discount - sum(labor) - sum(u * qty for u, (_, qty) in zip(unit, parts, strict=True)), 2
	)
	if remainder:
		if labor:
			i = max(range(len(labor)), key=lambda k: labor_rates[k])
			labor[i] = flt(labor[i] + remainder, 2)
		else:
			singles = [k for k, (_, qty) in enumerate(parts) if qty == 1]
			if singles:
				i = max(singles, key=lambda k: parts[k][0])
				unit[i] = flt(unit[i] + remainder, 2)

	return labor, unit

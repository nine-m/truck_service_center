# Copyright (c) 2026, Nine-m and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

# หน่วยที่หน้าต่างแนะนำแพ็คเกจ PM ส่งมา → ฟิลด์รอบของแพ็คเกจที่ใช้เทียบ
PM_INTERVAL_FIELDS = {"km": "service_interval_km", "hours": "pm_interval_hours"}

from truck_service_center.discounts import distribute_package_discount, percent_of


class ServicePackage(Document):
	def validate(self):
		self.validate_package_service_types()
		self.validate_pm_fields()
		self.populate_parts_from_service_types()
		self.calculate_totals()
		self.validate_pricing()

	def validate_package_service_types(self):
		"""ตรวจสอบว่ามีประเภทบริการในแพ็คเกจ"""
		if not self.package_service_types:
			frappe.throw("กรุณาเพิ่มประเภทบริการในแพ็คเกจอย่างน้อย 1 รายการ")

	def validate_pm_fields(self):
		"""แพ็คเกจ PM ต้องมีทั้งรหัสประเภทรถและรอบอย่างน้อยหนึ่งค่า — ไม่ใส่อะไรเลย = แพ็คเกจทั่วไป

		ตั้งครึ่ง ๆ กลาง ๆ ไม่ได้ทั้งสองทาง เพราะ get_pm_packages ต้องใช้ทั้งคู่ แพ็คเกจที่ขาดข้างใด
		ข้างหนึ่งจะไม่ถูกแนะนำเลย ทั้งที่ฟอร์มดูเหมือนตั้งค่าไว้แล้ว
		"""
		intervals = [cint(self.get(field)) for field in PM_INTERVAL_FIELDS.values()]
		if any(value < 0 for value in intervals):
			frappe.throw("รอบ PM (กม. / ชั่วโมงทำงาน) ต้องไม่ติดลบ")

		has_interval = any(value > 0 for value in intervals)
		if self.pm_truck_type and not has_interval:
			frappe.throw("แพ็คเกจ PM ต้องระบุรอบ กม. หรือ ชั่วโมงทำงาน อย่างน้อยหนึ่งค่า")
		if has_interval and not self.pm_truck_type:
			frappe.throw("ระบุรอบ PM แล้วต้องระบุรหัสประเภทรถ PM ด้วย — หรือล้างรอบทิ้งถ้าเป็นแพ็คเกจทั่วไป")

	def populate_parts_from_service_types(self):
		"""ดึงรายการอะไหล่จากประเภทบริการมาใส่ในตารางอะไหล่"""
		# เก็บรายการที่ user เพิ่มเอง (ไม่มี service_type)
		manual_parts = [p for p in self.package_parts if not p.service_type]

		# ล้างรายการที่มาจาก service type (จะสร้างใหม่)
		auto_parts = []
		for st_row in self.package_service_types:
			if not st_row.service_type:
				continue
			st_doc = frappe.get_doc("Service Type", st_row.service_type)
			for item in st_doc.items:
				auto_parts.append(
					{
						"service_type": st_row.service_type,
						"item_code": item.item_code,
						"item_name": item.item_name,
						"qty": item.qty,
						"uom": item.uom,
						"rate": item.rate,
						"amount": flt(item.qty) * flt(item.rate),
					}
				)

		# สร้างตารางอะไหล่ใหม่ = auto + manual
		self.package_parts = []
		for p in auto_parts:
			self.append("package_parts", p)
		for p in manual_parts:
			self.append(
				"package_parts",
				{
					"service_type": p.service_type,
					"item_code": p.item_code,
					"item_name": p.item_name,
					"qty": p.qty,
					"uom": p.uom,
					"rate": p.rate,
					"amount": flt(p.qty) * flt(p.rate),
				},
			)

	def calculate_totals(self):
		"""คำนวณยอดรวมและราคาแพ็คเกจ"""
		# คำนวณค่าแรงรวม
		total_labor = 0
		total_time = 0
		for st in self.package_service_types:
			total_labor += flt(st.labor_rate)
			total_time += flt(st.estimated_time)
		self.total_labor_rate = total_labor

		# คำนวณ estimated_duration (hours → seconds for Duration field)
		self.estimated_duration = int(total_time * 3600) if total_time else 0

		# คำนวณค่าอะไหล่รวม
		total_parts = 0
		for part in self.package_parts:
			part.amount = flt(part.qty) * flt(part.rate)
			total_parts += part.amount
		self.total_parts_amount = total_parts

		# ราคามาตรฐานรวม = ค่าแรง + ค่าอะไหล่
		total_standard = total_labor + total_parts
		self.total_standard_rate = total_standard

		# ราคาแพ็คเกจ (บาท) เป็นตัวหลัก % เป็นค่าที่คำนวณไว้แสดง — กติกาเดียวกับ resolve_line_discount
		# คิดราคาจาก % เฉพาะเมื่อ % ไม่ตรงกับราคาที่มีอยู่ (ผู้ใช้เพิ่งแก้ % หรือราคามาตรฐานเปลี่ยน
		# ซึ่งคง % ไว้) ไม่งั้นคีย์ราคา 5,000 จากราคามาตรฐาน 7,250 จะกลายเป็น 31.03% → 5,000.33
		if not 0 <= flt(self.discount_percent) <= 100:
			# ปล่อยค่าที่ผิดไว้ให้ validate_pricing ฟ้อง — ถ้าคำนวณต่อ % จะถูกปรับเป็น 0 เงียบ ๆ
			return

		if total_standard > 0:
			discount_amount = max(total_standard - flt(self.package_rate), 0) if self.package_rate else 0
			if flt(self.discount_percent) and percent_of(discount_amount, total_standard) != flt(
				self.discount_percent, 2
			):
				self.package_rate = flt(total_standard - total_standard * flt(self.discount_percent) / 100, 2)
			elif not self.package_rate:
				self.package_rate = total_standard

			# ราคาแพ็คเกจเท่ากับ/สูงกว่าราคามาตรฐาน = ไม่มีส่วนลด (ไม่คิดส่วนลดติดลบ)
			self.discount_percent = percent_of(
				max(total_standard - flt(self.package_rate), 0), total_standard
			)
		elif not self.package_rate:
			self.package_rate = total_standard
			self.discount_percent = 0

	def validate_pricing(self):
		"""ตรวจสอบความถูกต้องของราคาและส่วนลด"""
		if flt(self.discount_percent) < 0:
			frappe.throw("ส่วนลดต้องเป็นค่าบวก")

		if flt(self.discount_percent) > 100:
			frappe.throw("ส่วนลดไม่สามารถเกิน 100% ได้")

		if flt(self.package_rate) < 0:
			frappe.throw("ราคาแพ็คเกจต้องเป็นค่าบวก")

		if flt(self.package_rate) > flt(self.total_standard_rate):
			frappe.msgprint(
				msg="ราคาแพ็คเกจสูงกว่าราคามาตรฐานรวม",
				title="คำเตือน",
				indicator="orange",
			)

		# ตรวจความสอดคล้องเฉพาะกรณีที่มีส่วนลด — % ถูกปัด 2 ตำแหน่ง จึงเทียบที่ระดับ % ไม่ใช่ระดับบาท
		# ถ้าไม่ใส่ส่วนลด ให้ระบุราคาแพ็คเกจได้อิสระ (สูงกว่าราคามาตรฐานได้ แค่เตือน)
		if self.total_standard_rate > 0 and flt(self.discount_percent) > 0:
			calculated_rate = flt(self.total_standard_rate) * (1 - flt(self.discount_percent) / 100)
			discount = flt(self.total_standard_rate) - flt(self.package_rate)
			if percent_of(discount, self.total_standard_rate) != flt(self.discount_percent, 2):
				frappe.throw(
					f"ราคาแพ็คเกจไม่สอดคล้องกับส่วนลด<br>"
					f"ราคามาตรฐาน: {self.total_standard_rate:.2f}<br>"
					f"ส่วนลด: {self.discount_percent:.2f}%<br>"
					f"ราคาแพ็คเกจที่คำนวณได้: {calculated_rate:.2f}<br>"
					f"ราคาแพ็คเกจที่ระบุ: {self.package_rate:.2f}"
				)

	def get_discount_amount(self):
		"""จำนวนเงินส่วนลด = ราคามาตรฐาน - ราคาแพ็คเกจ (ราคาแพ็คเกจเป็นตัวหลัก)"""
		return flt(max(flt(self.total_standard_rate) - flt(self.package_rate), 0), 2)


@frappe.whitelist()
def get_package_details(package_name):
	"""ดึงข้อมูลแพ็คเกจพร้อมรายการประเภทบริการและอะไหล่"""
	if not package_name:
		return {}

	package = frappe.get_doc("Service Package", package_name)

	if not package.is_active:
		frappe.throw(f"แพ็คเกจ {package_name} ถูกปิดการใช้งานแล้ว")

	# ส่วนลดต่อบรรทัดเป็นบาท ให้ฟอร์มที่ดึงแพ็คเกจใส่ค่าเดียวกับฝั่ง server (apply_service_packages)
	labor_discounts, part_discounts = distribute_package_discount(package)

	service_types = []
	for st, discount in zip(package.package_service_types, labor_discounts, strict=True):
		service_types.append(
			{
				"service_type": st.service_type,
				"service_type_name": st.service_type_name,
				"service_type_group": st.service_type_group,
				"maintenance_type": st.maintenance_type,
				"labor_rate": st.labor_rate,
				"discount_amount": discount,
				"discount_percentage": percent_of(discount, st.labor_rate),
				"estimated_time": st.estimated_time,
			}
		)

	parts = []
	for p, discount in zip(package.package_parts, part_discounts, strict=True):
		parts.append(
			{
				"service_type": p.service_type,
				"item_code": p.item_code,
				"item_name": p.item_name,
				"qty": p.qty,
				"uom": p.uom,
				"rate": p.rate,
				"amount": p.amount,
				"discount_amount": discount,
				"discount_percentage": percent_of(discount, p.rate),
			}
		)

	return {
		"package_code": package.package_code,
		"package_name": package.package_name,
		"package_type": package.package_type,
		"package_rate": package.package_rate,
		"total_standard_rate": package.total_standard_rate,
		"total_labor_rate": package.total_labor_rate,
		"total_parts_amount": package.total_parts_amount,
		"discount_percent": package.discount_percent,
		"repair_time_hours": package.repair_time_hours,
		"discount_amount": package.get_discount_amount(),
		"validity_days": package.validity_days,
		"service_interval_km": package.service_interval_km,
		"pm_truck_type": package.pm_truck_type,
		"pm_interval_hours": package.pm_interval_hours,
		"max_services": package.max_services,
		"description": package.description,
		"service_types": service_types,
		"parts": parts,
	}


@frappe.whitelist()
def get_active_packages():
	"""ดึงรายการแพ็คเกจที่เปิดใช้งาน"""
	packages = frappe.get_all(
		"Service Package",
		filters={"is_active": 1},
		fields=[
			"name",
			"package_code",
			"package_name",
			"package_type",
			"package_rate",
			"discount_percent",
			"description",
		],
		order_by="package_type, package_rate",
	)
	return packages


def match_pm_packages(packages, reading, interval_field):
	"""แพ็คเกจที่ครบระยะ ณ เลขไมล์/ชั่วโมงทำงาน reading — หารรอบลงตัวคือครบระยะ

	reading ที่เข้าหลายรอบได้ทุกแพ็คเกจที่เข้า (50,000 กม. → ทั้งรอบ 10,000 และ 50,000)
	ไม่ปัดเลขให้ ผู้ใช้ใส่เลขกลมตามรอบเอง (325,759 → 330,000) แพ็คเกจรอบ 0 ถูกข้าม
	"""
	reading = cint(reading)
	if reading <= 0:
		return []

	matched = [
		pkg
		for pkg in packages
		if cint(pkg.get(interval_field)) > 0 and reading % cint(pkg.get(interval_field)) == 0
	]
	return sorted(matched, key=lambda pkg: cint(pkg.get(interval_field)))


@frappe.whitelist()
def get_pm_packages(pm_truck_type, reading, unit="km"):
	"""แพ็คเกจ PM ที่ใช้ได้ของรหัสประเภทรถ ณ เลขไมล์ (unit="km") หรือชั่วโมงทำงาน (unit="hours")"""
	interval_field = PM_INTERVAL_FIELDS.get(unit)
	if not interval_field:
		frappe.throw("หน่วยต้องเป็น km หรือ hours")
	if not pm_truck_type:
		frappe.throw("กรุณาเลือกรหัสประเภทรถ PM")
	if cint(reading) <= 0:
		frappe.throw("กรุณาระบุเลขไมล์หรือชั่วโมงทำงานมากกว่า 0")

	packages = frappe.get_all(
		"Service Package",
		filters={"is_active": 1, "pm_truck_type": pm_truck_type, interval_field: [">", 0]},
		fields=[
			"name",
			"package_code",
			"package_name",
			"package_rate",
			"discount_percent",
			"repair_time_hours",
			f"{interval_field} as pm_interval",
		],
	)
	return match_pm_packages(packages, reading, "pm_interval")

# Copyright (c) 2026, Nine-m and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class ServicePackage(Document):
	def validate(self):
		self.validate_package_service_types()
		self.populate_parts_from_service_types()
		self.calculate_totals()
		self.validate_pricing()

	def validate_package_service_types(self):
		"""ตรวจสอบว่ามีประเภทบริการในแพ็คเกจ"""
		if not self.package_service_types:
			frappe.throw("กรุณาเพิ่มประเภทบริการในแพ็คเกจอย่างน้อย 1 รายการ")

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

		# คำนวณส่วนลดและราคาแพ็คเกจ
		# ให้ discount_percent มีความสำคัญกว่า package_rate
		# เพราะ package_rate เป็น reqd จึงมีค่าเสมอ ถ้าเช็ค package_rate ก่อน
		# จะทำให้ branch ของ discount_percent ไม่มีทางถูกเรียก
		if self.discount_percent and total_standard > 0:
			discount_amount = total_standard * flt(self.discount_percent) / 100
			self.package_rate = total_standard - discount_amount
		elif self.package_rate and total_standard > 0:
			discount_amount = total_standard - flt(self.package_rate)
			# ราคาแพ็คเกจเท่ากับ/สูงกว่าราคามาตรฐาน = ไม่มีส่วนลด
			# (ไม่คิดส่วนลดติดลบ เพราะจะไปติด validate_pricing)
			self.discount_percent = (discount_amount / total_standard) * 100 if discount_amount > 0 else 0
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

		# ตรวจความสอดคล้องเฉพาะกรณีที่มีส่วนลด
		# ถ้าไม่ใส่ส่วนลด ให้ระบุราคาแพ็คเกจได้อิสระ (สูงกว่าราคามาตรฐานได้ แค่เตือน)
		if self.total_standard_rate > 0 and flt(self.discount_percent) > 0:
			calculated_rate = flt(self.total_standard_rate) * (1 - flt(self.discount_percent) / 100)
			rate_difference = abs(flt(self.package_rate) - calculated_rate)
			if rate_difference > 0.01:
				frappe.throw(
					f"ราคาแพ็คเกจไม่สอดคล้องกับส่วนลด<br>"
					f"ราคามาตรฐาน: {self.total_standard_rate:.2f}<br>"
					f"ส่วนลด: {self.discount_percent:.2f}%<br>"
					f"ราคาแพ็คเกจที่คำนวณได้: {calculated_rate:.2f}<br>"
					f"ราคาแพ็คเกจที่ระบุ: {self.package_rate:.2f}"
				)

	def get_discount_amount(self):
		"""คำนวณจำนวนเงินส่วนลด"""
		if self.discount_percent and self.total_standard_rate:
			return flt(self.total_standard_rate) * flt(self.discount_percent) / 100
		return 0


@frappe.whitelist()
def get_package_details(package_name):
	"""ดึงข้อมูลแพ็คเกจพร้อมรายการประเภทบริการและอะไหล่"""
	if not package_name:
		return {}

	package = frappe.get_doc("Service Package", package_name)

	if not package.is_active:
		frappe.throw(f"แพ็คเกจ {package_name} ถูกปิดการใช้งานแล้ว")

	service_types = []
	for st in package.package_service_types:
		service_types.append(
			{
				"service_type": st.service_type,
				"service_type_name": st.service_type_name,
				"service_type_group": st.service_type_group,
				"maintenance_type": st.maintenance_type,
				"labor_rate": st.labor_rate,
				"estimated_time": st.estimated_time,
			}
		)

	parts = []
	for p in package.package_parts:
		parts.append(
			{
				"service_type": p.service_type,
				"item_code": p.item_code,
				"item_name": p.item_name,
				"qty": p.qty,
				"uom": p.uom,
				"rate": p.rate,
				"amount": p.amount,
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
		"discount_amount": package.get_discount_amount(),
		"validity_days": package.validity_days,
		"service_interval_km": package.service_interval_km,
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

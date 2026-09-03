# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.contacts.doctype.address.address import get_address_display
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime, time_diff_in_hours

# ฟิลด์ของแถวอะไหล่ที่ห้ามแก้หลังใบเบิกถูก submit — ชุดเดียวกับที่ฝั่ง client ล็อกไว้
# (lock_rows_with_submitted_material_issue ใน service_order.js)
MATERIAL_ISSUE_LOCKED_TEXT_FIELDS = {
	"item_code": "รหัสสินค้า",
	"warehouse": "คลังสินค้า",
}
MATERIAL_ISSUE_LOCKED_NUMERIC_FIELDS = {
	"qty": "จำนวน",
	"rate": "ราคา",
}

# ฟิลด์ที่ต้องกรอกก่อน submit ใบสั่งงาน (นอกเหนือจาก reqd ในฟอร์ม) — ใช้ label จาก meta
# จะได้ไม่ต้องเขียนชื่อภาษาไทยซ้ำกับที่ตั้งไว้ใน doctype
SUBMIT_REQUIRED_FIELDS = ("fuel_level_in", "fuel_level_out", "technician")

# ช่องช่างของ "แถวงาน" (Service Order Service Type) — แบน 10 ช่องตามที่ผู้ใช้เลือก
ROW_TECHNICIAN_FIELDS = tuple(f"technician_{i}" for i in range(1, 11))

# ช่องช่างระดับใบงาน — ช่องแรกชื่อ technician เฉย ๆ ที่เหลือมีเลขต่อท้าย
PARENT_TECHNICIAN_FIELDS = ("technician", *(f"technician_{i}" for i in range(2, 11)))

# สถานะที่ถือว่าใบงานยัง "เปิด" อยู่ — ใช้หาว่าช่องจอดถูกใบอื่นใช้ค้างไว้หรือเปล่า
# ประกาศที่นี่ ไม่ import EDITABLE_STATUSES จาก technician_portal เพราะฝั่งนั้น
# import receive_vehicle จากไฟล์นี้อยู่แล้ว (จะกลายเป็น circular import)
OPEN_STATUSES = ("Draft", "In Progress", "On Hold")


def get_default_selling_rate(item_code, price_list=None):
	"""ราคาขายเริ่มต้นของสินค้า: Item Price (selling) → standard_rate → valuation_rate

	ใช้เป็น fallback ตอนคำนวณยอดเมื่อแถวอะไหล่ไม่มีราคา — ราคาทุน (valuation_rate)
	เป็นทางเลือกสุดท้ายเท่านั้น เพื่อไม่ให้เผลอขายเท่าทุนทั้งที่ตั้งราคาขายไว้แล้ว

	ฝั่ง client (get_item_rate / get_item_by_barcode) ต้องใช้ลำดับราคาชุดเดียวกันนี้
	ไม่งั้นราคาที่เห็นบนฟอร์มจะไม่ตรงกับยอดที่ได้หลังกด save
	"""
	if not item_code:
		return 0

	if not price_list:
		price_list = (
			frappe.db.get_single_value("Selling Settings", "selling_price_list") or "Standard Selling"
		)
	price = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "selling": 1},
		"price_list_rate",
	)
	if price:
		return flt(price)

	item = frappe.db.get_value("Item", item_code, ["standard_rate", "valuation_rate"], as_dict=1)
	if not item:
		return 0
	return flt(item.standard_rate) or flt(item.valuation_rate)


class ServiceOrder(Document):
	def validate(self):
		self.validate_status_change()
		self.stamp_receive_on_progress()
		self.set_tax_defaults()
		self.set_address_display()
		self.check_material_issue_items()
		self.apply_service_packages()
		self.validate_service_type_removal()
		self.remove_orphan_service_type_items()
		self.calculate_totals()
		self.apply_default_bay()
		self.sync_row_technicians_to_parent()
		self.compute_actual_time()
		self.warn_bay_issues()
		self.calculate_wht()
		self.update_payment_status()
		self.update_material_issue_status()

	def validate_status_change(self):
		"""ป้องกันการย้อนสถานะจาก In Progress กลับเป็น Draft"""
		if self.is_new():
			return

		old_status = self.get_doc_before_save()
		if old_status and old_status.status == "In Progress" and self.status == "Draft":
			frappe.throw("ไม่สามารถย้อนสถานะจาก In Progress กลับเป็น Draft ได้", title="ไม่สามารถเปลี่ยนสถานะได้")

	def stamp_receive_on_progress(self):
		"""ถือว่าการเปลี่ยนสถานะเป็น In Progress คือการรับรถ และบันทึกเวลานั้นไว้

		ปุ่ม "รับรถ" (receive_vehicle) ยังเป็นทางหลักที่ผ่านการตรวจน้ำมันรับเข้า
		แต่ status เป็น Select ที่แก้ด้วยมือในฟอร์มได้ ถ้าแก้ตรง ๆ ก็ให้ stamp ให้ด้วย
		เพื่อให้ received_date สะท้อนเวลาที่เริ่มงานจริงเสมอ

		ไม่เขียนทับค่าเดิม — receive_vehicle stamp มาก่อนเรียก save() อยู่แล้ว
		และจำกัดเฉพาะตอนที่ status เปลี่ยนจริง เพื่อไม่ให้เอกสารเก่าที่ค้างสถานะ
		In Progress อยู่ ถูก stamp เวลาผิดตอนบันทึกเรื่องอื่น
		"""
		if self.status != "In Progress" or self.received_date:
			return

		if not (self.is_new() or self.has_value_changed("status")):
			return

		self.received_by = frappe.session.user
		self.received_date = now_datetime()

	def set_address_display(self):
		"""ตั้งค่าการแสดงผลที่อยู่สำหรับ billing และ shipping address

		คำนวณใหม่เฉพาะตอนที่ฟิลด์ที่อยู่เปลี่ยนจริง เพราะ get_address_display เรียก
		Address.check_permission() ซึ่ง hook ของ Frappe ไปเช็คสิทธิ์ต่อบน doctype ที่ Address
		ผูกอยู่ (Customer) — role อย่าง Technician ที่ไม่มี read บน Customer จะ save ใบสั่งงาน
		ที่มีที่อยู่ไม่ได้เลย ทั้งที่ไม่ได้ไปยุ่งกับที่อยู่
		"""
		if self.is_new() or self.has_value_changed("customer_address"):
			self.address_display = get_address_display(self.customer_address) if self.customer_address else ""

		if self.is_new() or self.has_value_changed("shipping_address_name"):
			self.shipping_address = (
				get_address_display(self.shipping_address_name) if self.shipping_address_name else ""
			)

	def check_material_issue_items(self):
		"""ห้ามลบหรือแก้แถวอะไหล่ที่ใบเบิกถูก submit ไปแล้ว

		ต้องตรวจที่เอกสารแม่ เพราะ Frappe ไม่เรียก validate ของ child doctype controller
		(run_before_save_methods เรียก run_method("validate") ของ parent เท่านั้น)
		"""
		if self.is_new():
			return

		# ดึงข้อมูลเดิมจาก database
		old_doc = self.get_doc_before_save()
		if not old_doc:
			return

		current_rows = {item.name: item for item in self.service_items if item.name}

		for old_item in old_doc.service_items:
			if not old_item.name or not old_item.material_issue:
				continue

			# ล็อกเฉพาะแถวที่ใบเบิก submit แล้ว — ใบเบิก Draft ยังแก้ตามกันได้
			if frappe.db.get_value("Stock Entry", old_item.material_issue, "docstatus") != 1:
				continue

			label = old_item.item_name or old_item.item_code
			row = current_rows.get(old_item.name)

			if row is None:
				frappe.throw(
					f"ไม่สามารถลบรายการ '{label}' ได้ "
					f"เนื่องจากใบเบิกอะไหล่ {old_item.material_issue} ถูก submit ไปแล้ว<br>"
					f"กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการลบรายการ",
					title="ไม่สามารถลบรายการได้",
				)

			changed_fields = [
				th_label
				for field, th_label in MATERIAL_ISSUE_LOCKED_TEXT_FIELDS.items()
				if (old_item.get(field) or "") != (row.get(field) or "")
			]
			changed_fields += [
				th_label
				for field, th_label in MATERIAL_ISSUE_LOCKED_NUMERIC_FIELDS.items()
				if flt(old_item.get(field)) != flt(row.get(field))
			]

			if changed_fields:
				frappe.throw(
					f"ไม่สามารถแก้ {', '.join(changed_fields)} ของรายการ '{label}' ได้ "
					f"เนื่องจากใบเบิกอะไหล่ {old_item.material_issue} ถูก submit ไปแล้ว<br>"
					f"กรุณายกเลิกใบเบิกอะไหล่ก่อนทำการแก้ไข",
					title="ไม่สามารถแก้ไขรายการได้",
				)

	def apply_service_packages(self):
		"""นำรายการบริการและอะไหล่จากแพ็คเกจมาใส่อัตโนมัติ (รองรับหลาย package)

		Logic:
		- ตรวจสอบว่ามี service_packages rows ที่ยังไม่ได้ดึงข้อมูล (ไม่มี service_type/item ที่ผูกกับ package นี้)
		- สำหรับแต่ละ package → ดึง service types + parts → เพิ่มในตาราง service_types/service_items
		- ใส่ discount จาก package ให้แต่ละ row
		- เมื่อลบ package → ลบ service_types/service_items ที่ผูกกับ package นั้น (cascade delete)
		"""
		if not self.service_packages:
			return

		# รวบรวม package names ที่ยังอยู่ในตาราง
		current_package_names = set()
		for pkg_row in self.service_packages:
			if pkg_row.service_package:
				current_package_names.add(pkg_row.service_package)

		# Cascade delete: ลบ service_types/service_items ที่ผูกกับ package ที่ถูกลบออก
		self.service_types = [
			st
			for st in self.service_types
			if not st.service_package or st.service_package in current_package_names
		]
		self.service_items = [
			si
			for si in self.service_items
			if not si.service_package or si.service_package in current_package_names
		]

		# สำหรับแต่ละ package ตรวจสอบว่าดึงข้อมูลแล้วหรือยัง
		for pkg_row in self.service_packages:
			if not pkg_row.service_package:
				continue

			pkg_name = pkg_row.service_package

			# แพ็คเกจนี้ถูกดึงข้อมูลแล้วหรือยัง — ต้องดูทั้งสองตาราง เพราะถ้าดู service_types
			# อย่างเดียว การลบประเภทบริการของแพ็คเกจจนหมดจะทำให้ดึงซ้ำ อะไหล่จึงบวกเป็นสองเท่า
			already_applied = any(st.service_package == pkg_name for st in self.service_types) or any(
				si.service_package == pkg_name for si in self.service_items
			)

			if already_applied:
				continue

			# ดึงข้อมูลจาก package
			package = frappe.get_doc("Service Package", pkg_name)

			if not package.is_active:
				frappe.throw(f"แพ็คเกจ {pkg_name} ถูกปิดการใช้งานแล้ว")

			discount_pct = flt(package.discount_percent)

			# เพิ่ม service types จาก package
			for st in package.package_service_types:
				self.append(
					"service_types",
					{
						"service_type": st.service_type,
						"service_type_group": st.service_type_group,
						"maintenance_type": st.maintenance_type,
						"estimated_time": st.estimated_time,
						"labor_charges": st.labor_rate,
						"discount_percentage": discount_pct,
						"service_package": pkg_name,
					},
				)

			# เพิ่ม parts จาก package
			default_warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
			for part in package.package_parts:
				self.append(
					"service_items",
					{
						"item_code": part.item_code,
						"item_name": part.item_name,
						"qty": part.qty,
						"uom": part.uom,
						"rate": part.rate,
						"discount_percentage": discount_pct,
						"warehouse": default_warehouse,
						"service_package": pkg_name,
						"service_type": part.service_type,
					},
				)

	def validate_service_type_removal(self):
		"""ห้ามลบประเภทบริการที่อะไหล่ของมันถูกเบิกไปแล้ว

		remove_orphan_service_type_items() ไม่ยอมลบแถวที่มีใบเบิก submit ถ้าปล่อยให้ลบ
		ประเภทบริการได้ อะไหล่จะค้างเป็นแถวไร้ที่มา ใบงานกับใบเบิกจึงไม่ตรงกัน
		คู่กับ before_service_types_remove ฝั่ง client — ที่นี่คือด่านจริง เพราะครอบคลุม
		การลบแพ็คเกจ (ซึ่งพาประเภทบริการหายไปด้วย) และการบันทึกผ่าน API ด้วย

		ตรวจเฉพาะ "ตอนที่ลบ" โดยเทียบกับเอกสารก่อนบันทึก ไม่ใช่ตรวจสถานะปัจจุบัน
		มิฉะนั้นเอกสารที่ค้างสถานะนี้อยู่ก่อนแล้วจะบันทึกไม่ได้อีกเลย
		"""
		old_doc = self.get_doc_before_save()
		if not old_doc:
			return

		removed = {st.service_type for st in old_doc.service_types if st.service_type} - {
			st.service_type for st in self.service_types if st.service_type
		}
		if not removed:
			return

		# ถามสถานะจาก Stock Entry ตรง ๆ แบบเดียวกับ check_material_issue_items
		# ไม่เชื่อ material_issue_status ที่แคชไว้ในแถว เพราะ update_material_issue_status()
		# เพิ่งจะรีเฟรชค่านั้นตอนท้าย validate
		candidates = [
			item for item in self.service_items if item.service_type in removed and item.material_issue
		]
		if not candidates:
			return

		submitted = set(
			frappe.get_all(
				"Stock Entry",
				filters={"name": ["in", list({item.material_issue for item in candidates})], "docstatus": 1},
				pluck="name",
			)
		)

		blocked = {}
		for item in candidates:
			if item.material_issue in submitted:
				blocked.setdefault(item.service_type, set()).add(item.material_issue)

		if not blocked:
			return

		lines = "<br>".join(
			f"• {service_type} — ใบเบิก {', '.join(sorted(issues))}"
			for service_type, issues in sorted(blocked.items())
		)
		frappe.throw(
			f"ลบประเภทบริการต่อไปนี้ไม่ได้ เพราะอะไหล่ถูกเบิกไปแล้ว<br>{lines}<br><br>กรุณายกเลิกใบเบิกอะไหล่ก่อน",
			title="ไม่สามารถลบประเภทบริการได้",
		)

	def remove_orphan_service_type_items(self):
		"""ลบอะไหล่ที่ดึงมาจากประเภทบริการซึ่งถูกลบออกจากตารางแล้ว

		คู่กับ remove_orphan_service_type_items() ฝั่ง client — ทำซ้ำที่ server เพื่อให้
		กฎยังทำงานเมื่อบันทึกผ่าน API/พอร์ทัล ไม่ใช่แค่ผ่านหน้า desk

		อะไหล่ที่ service_type ว่างคือของที่เพิ่มเอง (รวมถึงข้อมูลเก่าก่อนมีฟิลด์นี้)
		จะไม่ถูกแตะ ส่วนแถวที่มีใบเบิกซึ่ง submit แล้วก็ลบไม่ได้ ต้องยกเลิกใบเบิกก่อน
		"""
		remaining = {st.service_type for st in self.service_types if st.service_type}

		kept = []
		for item in self.service_items:
			if not item.service_type or item.service_type in remaining:
				kept.append(item)
				continue
			if item.material_issue and item.material_issue_status == "Submitted":
				kept.append(item)
				continue

		self.service_items = kept

		for idx, item in enumerate(self.service_items, start=1):
			item.idx = idx

	def set_tax_defaults(self):
		"""ตั้งค่าภาษีเริ่มต้นจาก Settings"""
		settings = frappe.get_single("Truck Service Center Settings")
		if not self.tax_type:
			self.tax_type = settings.default_tax_type or "ราคาแยก VAT"
		if not self.vat_rate:
			self.vat_rate = flt(settings.vat_rate) or 7

	def calculate_totals(self):
		"""คำนวณยอดรวมทั้งหมด"""
		# คำนวณยอดรวมอะไหล่ (พร้อมส่วนลดระดับบรรทัด)
		self.total_parts_amount = 0
		for item in self.service_items:
			# ถ้าไม่มี rate ให้ดึงราคาขาย (Item Price → standard_rate → ราคาทุนเป็นทางสุดท้าย)
			if not item.rate:
				item.rate = get_default_selling_rate(item.item_code)

			# คำนวณส่วนลดระดับบรรทัด
			self._calculate_line_discount(item)
			self.total_parts_amount += flt(item.amount)

		# คำนวณค่าแรงรวมและเวลารวมจากประเภทบริการทั้งหมด
		self.labor_charges = 0
		self.estimated_time = 0
		for service_type in self.service_types:
			# คำนวณส่วนลดระดับบรรทัดสำหรับค่าแรง
			self._calculate_service_type_discount(service_type)
			self.labor_charges += flt(service_type.amount)
			self.estimated_time += flt(service_type.estimated_time)

		# คำนวณยอดก่อนภาษี (subtotal หลังหักส่วนลดระดับเอกสาร)
		subtotal = flt(self.total_parts_amount) + flt(self.labor_charges) - flt(self.discount_amount)

		# คำนวณภาษีตามประเภท
		vat_rate = flt(self.vat_rate)

		if self.tax_type == "ราคารวม VAT" and vat_rate:
			# ราคารวม VAT แล้ว → แยก VAT ออกจากยอดรวม
			self.tax_amount = flt(subtotal * vat_rate / (100 + vat_rate), 2)
			self.net_total = flt(subtotal - self.tax_amount, 2)
			self.total_amount = flt(subtotal, 2)
		elif self.tax_type == "ราคาแยก VAT" and vat_rate:
			# ราคาแยก VAT → คิด VAT เพิ่มจากยอดสุทธิ
			self.net_total = flt(subtotal, 2)
			self.tax_amount = flt(subtotal * vat_rate / 100, 2)
			self.total_amount = flt(subtotal + self.tax_amount, 2)
		else:
			# ไม่คิด VAT
			self.net_total = flt(subtotal, 2)
			self.tax_amount = 0
			self.total_amount = flt(subtotal, 2)

		# คำนวณยอดคงค้าง
		self.outstanding_amount = flt(self.total_amount) - flt(self.paid_amount)

	def _calculate_line_discount(self, item):
		"""คำนวณส่วนลดระดับบรรทัดสำหรับ Service Order Item

		Logic (inspired by ERPNext Sales Order):
		- ถ้ากรอก discount_percentage → คำนวณ discount_amount จาก rate
		- ถ้ากรอก discount_amount (โดยไม่มี discount_percentage) → คำนวณ discount_percentage จาก rate
		- amount = (rate - discount_per_unit) * qty
		"""
		rate = flt(item.rate)
		qty = flt(item.qty)

		if flt(item.discount_percentage) > 0:
			# คำนวณ discount_amount จาก percentage
			item.discount_amount = flt(rate * flt(item.discount_percentage) / 100, 2)

		if flt(item.discount_amount) > 0 and rate > 0 and not flt(item.discount_percentage):
			# คำนวณ discount_percentage จาก amount (ถ้ายังไม่มี percentage)
			item.discount_percentage = flt(flt(item.discount_amount) / rate * 100, 2)

		# คำนวณ amount หลังส่วนลด
		discount_per_unit = flt(item.discount_amount)
		net_rate = flt(rate - discount_per_unit, 2)
		if net_rate < 0:
			net_rate = 0
		item.amount = flt(net_rate * qty, 2)

	def _calculate_service_type_discount(self, service_type):
		"""คำนวณส่วนลดระดับบรรทัดสำหรับ Service Order Service Type

		Logic:
		- ถ้ากรอก discount_percentage → คำนวณ discount_amount จาก labor_charges
		- ถ้ากรอก discount_amount → คำนวณ discount_percentage จาก labor_charges
		- amount = labor_charges - discount_amount
		"""
		labor = flt(service_type.labor_charges)

		if flt(service_type.discount_percentage) > 0:
			service_type.discount_amount = flt(labor * flt(service_type.discount_percentage) / 100, 2)

		if flt(service_type.discount_amount) > 0 and labor > 0 and not flt(service_type.discount_percentage):
			service_type.discount_percentage = flt(flt(service_type.discount_amount) / labor * 100, 2)

		discount = flt(service_type.discount_amount)
		net_labor = flt(labor - discount, 2)
		if net_labor < 0:
			net_labor = 0
		service_type.amount = flt(net_labor, 2)

	def calculate_wht(self):
		"""คำนวณภาษีหัก ณ ที่จ่าย (ลูกค้านิติบุคคลหักจากค่าบริการ ปกติ 3%)

		ฐานคำนวณคือยอดก่อน VAT:
		- "ค่าแรงเท่านั้น" (แยกค่าแรง/อะไหล่ในบิล) — สัดส่วนค่าแรงของ subtotal
		- "ทั้งใบ" (งานจ้างเหมา) — subtotal ทั้งหมด
		ส่วนลดท้ายบิลถูกเฉลี่ยตามสัดส่วน และถ้าราคารวม VAT จะถอด VAT ออกก่อน
		"""
		if not self.apply_wht:
			self.wht_amount = 0
			self.net_payment_amount = flt(self.total_amount)
			return

		if not flt(self.wht_rate):
			settings = frappe.get_single("Truck Service Center Settings")
			self.wht_rate = flt(settings.default_wht_rate) or 3

		labor = flt(self.labor_charges)
		parts = flt(self.total_parts_amount)
		gross = labor + parts
		subtotal = gross - flt(self.discount_amount)

		if self.wht_base == "ทั้งใบ (ค่าแรง+อะไหล่)":
			base = subtotal
		else:
			base = subtotal * labor / gross if gross else 0

		if self.tax_type == "ราคารวม VAT" and flt(self.vat_rate):
			base = base * 100 / (100 + flt(self.vat_rate))

		self.wht_amount = flt(base * flt(self.wht_rate) / 100, 2)
		self.net_payment_amount = flt(flt(self.total_amount) - self.wht_amount, 2)

	def update_payment_status(self):
		"""อัพเดทสถานะการชำระเงิน"""
		if flt(self.paid_amount) == 0:
			self.payment_status = "Unpaid"
		elif flt(self.paid_amount) >= flt(self.total_amount):
			self.payment_status = "Paid"
		else:
			self.payment_status = "Partially Paid"

	def update_material_issue_status(self):
		"""อัพเดทสถานะ Material Issue ในแต่ละ Item"""
		for item in self.service_items:
			if item.material_issue:
				# ดึงสถานะจาก Stock Entry
				status = frappe.db.get_value("Stock Entry", item.material_issue, "docstatus")
				if status == 0:
					item.material_issue_status = "Draft"
				elif status == 1:
					item.material_issue_status = "Submitted"
				elif status == 2:
					item.material_issue_status = "Cancelled"
			else:
				item.material_issue_status = None

	# ── ช่องจอด / ช่างรายงาน / เวลาจริง ────────────────────────────────────────

	def apply_default_bay(self):
		"""แถวงานที่ไม่ได้ระบุช่องจอดเอง ให้ใช้ช่องจอดหลักของใบงาน

		เติมตอน save เท่านั้น — แก้ช่องจอดหลักภายหลังจะมีผลเฉพาะแถวที่ยังว่างอยู่
		แถวที่หัวหน้าช่างเจาะจงไว้แล้วจะไม่ถูกทับ
		"""
		if not self.service_bay:
			return

		for row in self.service_types:
			if not row.service_bay:
				row.service_bay = self.service_bay

	def sync_row_technicians_to_parent(self):
		"""รวมช่างจากทุกแถวงานขึ้นมาไว้ที่ระดับใบงาน

		วางไว้ใน validate จึงได้ sync ทั้งตอนแก้ใน desk และตอนพอร์ทัลเรียก doc.save()
		โดยไม่ต้องเขียนโค้ดซ้ำสองที่

		เป็นการ sync ทางเดียว (แถว → ใบงาน) และไม่เคยลบช่างออกจากใบงาน เพราะช่าง
		ระดับใบงานอาจถูกกรอกเองโดยไม่ได้ผูกกับงานรายการไหน
		"""
		on_rows = []
		for row in self.service_types:
			for fieldname in ROW_TECHNICIAN_FIELDS:
				user = row.get(fieldname)
				if user and user not in on_rows:
					on_rows.append(user)

		if not on_rows:
			return

		already = {self.get(f) for f in PARENT_TECHNICIAN_FIELDS if self.get(f)}
		pending = [user for user in on_rows if user not in already]
		if not pending:
			return

		free = [f for f in PARENT_TECHNICIAN_FIELDS if not self.get(f)]
		for fieldname, user in zip(free, pending, strict=False):
			self.set(fieldname, user)

		overflow = pending[len(free) :]
		if overflow:
			frappe.msgprint(
				"ช่างระดับใบงานเต็ม 10 คนแล้ว ช่างต่อไปนี้ยังอยู่เฉพาะในแถวงาน: " + ", ".join(overflow),
				indicator="orange",
			)

	def compute_actual_time(self):
		"""เวลาทำงานจริง = เวลาเริ่มแรกสุด → เวลาจบท้ายสุด ของงานทุกรายการ

		เป็นเวลาแบบ wall-clock งานที่ทำขนานกันจึงไม่ถูกนับซ้ำ (ต่างจาก estimated_time
		ที่เป็นผลรวมของทุกงาน) ส่วนการคิดเงินไม่ได้ใช้เวลาเลย ใช้ labor_charges ตรง ๆ

		ใบเก่าที่ไม่มี timestamp สักอันจะไม่ถูกแตะ — ค่าที่กรอกมือไว้เดิมยังอยู่
		ทำให้ยัง submit ผ่านด่าน actual_time > 0 ใน before_submit ได้ตามเดิม
		"""
		starts = [row.start_time for row in self.service_types if row.start_time]
		ends = [row.end_time for row in self.service_types if row.end_time]

		if not starts and not ends:
			return

		if not starts or not ends:
			return

		self.actual_time = flt(time_diff_in_hours(max(ends), min(starts)), 2)

	def warn_bay_issues(self):
		"""เตือนเรื่องช่องจอดอย่างเดียว ไม่บล็อกการบันทึก (ตามที่ผู้ใช้ยืนยัน)"""
		for warning in get_bay_warnings(self):
			frappe.msgprint(warning, indicator="orange")

	def on_submit(self):
		"""เมื่อ submit ให้อัพเดทข้อมูลรถ และปรับสถานะ Service Appointment"""
		self.update_vehicle_info()
		self.complete_linked_service_appointment()

	def on_cancel(self):
		"""เมื่อยกเลิก ให้คืนข้อมูลบริการของรถจากใบงานที่เหลืออยู่"""
		self.revert_vehicle_info()

	def revert_vehicle_info(self):
		"""คำนวณข้อมูลบริการล่าสุดของรถใหม่จากใบสั่งงานที่ยัง submit อยู่

		ตอน submit เราเขียน last_service_date/mileage + current_mileage ทับลงรถ
		(update_vehicle_info) — เมื่อใบนั้นถูกยกเลิก เลขจากใบที่ยกเลิกต้องไม่ค้าง
		อยู่บนรถ จึงย้อนไปใช้ค่าจากใบงานล่าสุดที่เหลือ หรือล้างถ้าไม่มีแล้ว
		"""
		if not self.vehicle or not frappe.db.exists("Vehicle", self.vehicle):
			return

		last = frappe.get_all(
			"Service Order",
			filters={"vehicle": self.vehicle, "docstatus": 1, "name": ["!=", self.name]},
			fields=["service_date", "current_mileage"],
			order_by="service_date desc, modified desc",
			limit=1,
		)

		vehicle = frappe.get_doc("Vehicle", self.vehicle)

		if last:
			vehicle.last_service_date = last[0].service_date
			vehicle.last_service_mileage = last[0].current_mileage
		else:
			vehicle.last_service_date = None
			vehicle.last_service_mileage = None
			# calculate_next_service ไม่ล้างค่าให้เมื่อไม่มีประวัติ — ล้างเอง
			vehicle.next_service_due = None
			vehicle.next_service_mileage = None

		# คืนเลขไมล์ปัจจุบันเฉพาะกรณีที่ค่าบนรถมาจากใบที่ถูกยกเลิกนี้
		# (ถ้ามีคนอัพเดทเลขไมล์ทีหลัง อย่าไปทับ)
		if self.current_mileage and flt(vehicle.current_mileage) == flt(self.current_mileage):
			vehicle.current_mileage = last[0].current_mileage if last else None

		vehicle.calculate_next_service()
		vehicle.save()
		frappe.msgprint(f"คืนข้อมูลบริการของรถ {self.vehicle} จากใบงานที่เหลืออยู่แล้ว")

	def complete_linked_service_appointment(self):
		"""ค้นหา Service Appointment ที่ผูกกับ Service Order นี้ แล้วปรับสถานะเป็น Completed"""
		appointments = frappe.get_all(
			"Service Appointment",
			filters={"service_order": self.name, "docstatus": 1},
			pluck="name",
		)
		for appt_name in appointments:
			frappe.db.set_value("Service Appointment", appt_name, "status", "Completed")

	def before_submit(self):
		"""ก่อน submit ให้ตรวจสอบเงื่อนไขและตั้งสถานะเป็น Completed"""
		# 1. ต้องมีการสร้าง service type อย่างน้อย 1 รายการ
		if not self.service_types:
			frappe.throw("กรุณาเพิ่มประเภทบริการอย่างน้อย 1 รายการก่อน Submit")

		# 2. ราคายอดรวมทั้งหมดต้องมากกว่า 0
		if flt(self.total_amount) <= 0:
			frappe.throw("ยอดรวมทั้งหมดต้องมากกว่า 0")

		# 3. เวลาทำงานจริงต้องมากกว่า 0
		if flt(self.actual_time) <= 0:
			frappe.throw("กรุณาระบุเวลาทำงานจริงที่มากกว่า 0")

		# 4. ข้อมูลรับรถ/ผู้รับผิดชอบต้องครบ
		self.validate_required_fields_for_submit()

		# 5. ตรวจสอบ Material Issue ของ stock items
		self.validate_material_issues_for_submit()

		self.status = "Completed"

	def validate_required_fields_for_submit(self):
		"""ฟิลด์ที่ต้องกรอกก่อนปิดงาน — รวบให้ครบแล้วฟ้องทีเดียว จะได้ไม่ต้องแก้ทีละรอบ"""
		missing = [
			self.meta.get_label(fieldname) for fieldname in SUBMIT_REQUIRED_FIELDS if not self.get(fieldname)
		]

		if missing:
			frappe.throw(
				"กรุณาระบุข้อมูลต่อไปนี้ก่อน Submit:<br>" + "<br>".join(f"• {label}" for label in missing),
				title="ข้อมูลไม่ครบ",
			)

	def validate_material_issues_for_submit(self):
		"""กัน submit ถ้าใบเบิกอะไหล่ยังไม่ครบหรือไม่ตรงกับรายการในใบสั่งงาน"""
		problems = collect_material_issue_problems(self)
		errors = []

		if problems["items_without_mi"]:
			errors.append(
				"รายการอะไหล่ต่อไปนี้ยังไม่มีใบเบิกอะไหล่ (Material Issue):<br>"
				+ "<br>".join(f"• {row['label']}" for row in problems["items_without_mi"])
			)

		if problems["unsubmitted_mis"]:
			mi_list = [f"• {mi} (สถานะ: {status})" for mi, status in problems["unsubmitted_mis"].items()]
			errors.append(
				"ใบเบิกอะไหล่ต่อไปนี้ยังไม่ได้ Submit:<br>"
				+ "<br>".join(mi_list)
				+ "<br><br>กรุณา Submit ใบเบิกอะไหล่ทั้งหมดก่อน Submit Service Order"
			)

		if problems["missing_lines"]:
			errors.append(
				"รายการอะไหล่ต่อไปนี้ไม่มีบรรทัดที่ตรงกันในใบเบิก:<br>"
				+ "<br>".join(
					f"• {row['label']} → {row['material_issue']}" for row in problems["missing_lines"]
				)
				+ "<br><br>กรุณายกเลิกใบเบิกแล้วเบิกใหม่ให้ตรงกับรายการ"
			)

		if problems["qty_mismatches"]:
			errors.append(
				"จำนวนอะไหล่ในใบสั่งงานไม่ตรงกับจำนวนที่เบิกจริง:<br>"
				+ "<br>".join(
					f"• {row['label']}: ใบสั่งงาน {row['ordered']} / เบิกจริง {row['issued']}"
					+ f" ({row['material_issue']})"
					for row in problems["qty_mismatches"]
				)
				+ "<br><br>กรุณาแก้จำนวนให้ตรงกัน หรือยกเลิกใบเบิกแล้วเบิกใหม่"
			)

		if errors:
			frappe.throw("<br><br>".join(errors), title="ไม่สามารถ Submit ได้")

	def update_vehicle_info(self):
		"""อัพเดทข้อมูลรถหลังการบริการ"""
		if self.vehicle and self.current_mileage:
			vehicle = frappe.get_doc("Vehicle", self.vehicle)
			vehicle.update_service_info(self)
			frappe.msgprint(f"อัพเดทข้อมูลรถ {self.vehicle} เรียบร้อยแล้ว")

	def create_sales_invoice(self):
		"""สร้างใบแจ้งหนี้"""
		if self.sales_invoice:
			frappe.throw("มีการสร้าง Sales Invoice ไปแล้ว")

		# ดึงการตั้งค่าจาก Settings
		settings = frappe.get_single("Truck Service Center Settings")

		# ดึง company
		company = (
			settings.default_company
			or frappe.defaults.get_defaults().get("company")
			or frappe.db.get_single_value("Global Defaults", "default_company")
		)

		sales_invoice = frappe.new_doc("Sales Invoice")
		# ใบกำกับภาษีไทยต้องแสดงยอดตามจริง (รวมสตางค์) ห้ามปัดเศษ
		sales_invoice.disable_rounded_total = 1
		sales_invoice.customer = self.customer
		sales_invoice.company = company
		sales_invoice.posting_date = self.service_date
		sales_invoice.set_posting_time = 1
		sales_invoice.due_date = self.service_date

		# ใช้ Payment Terms Template ถ้ามีการตั้งค่า
		if settings.payment_terms_template:
			sales_invoice.payment_terms_template = settings.payment_terms_template

		# เพิ่มรายการบริการและอะไหล่ (พร้อมส่วนลดระดับบรรทัด)
		for item in self.service_items:
			if item.item_code:
				original_rate = flt(item.rate)
				has_discount = flt(item.discount_percentage) > 0 or flt(item.discount_amount) > 0

				si_item = {
					"item_code": item.item_code,
					"item_name": item.item_name or "",
					"description": item.description or "",
					"qty": flt(item.qty) or 1,
					"uom": item.uom,
					"warehouse": item.warehouse or settings.default_warehouse,
					"expense_account": item.expense_account or settings.default_expense_account,
					"cost_center": item.cost_center or settings.default_cost_center,
					"income_account": settings.default_income_account,
				}

				if has_discount and original_rate > 0:
					# ตั้ง price_list_rate = ราคาเต็ม เพื่อให้ SI แสดงส่วนลดได้ถูกต้อง
					# ERPNext คำนวณ: rate = price_list_rate * (1 - discount_percentage / 100)
					si_item["price_list_rate"] = original_rate
					si_item["discount_percentage"] = flt(item.discount_percentage)
					si_item["discount_amount"] = flt(item.discount_amount)
					# rate หลังส่วนลด
					si_item["rate"] = flt(original_rate - flt(item.discount_amount), 2)
				else:
					si_item["rate"] = original_rate

				sales_invoice.append("items", si_item)

		# เพิ่มรายการ Service Types (ค่าแรงแยกตามประเภทบริการ)
		if self.service_types:
			for service_type_row in self.service_types:
				if flt(service_type_row.labor_charges) > 0:
					# ตรวจสอบว่า Service Type ผูกกับ Item หรือไม่
					service_type_item = frappe.db.get_value(
						"Service Type",
						service_type_row.service_type,
						["item_code", "service_type_name", "income_account", "cost_center"],
						as_dict=1,
					)

					if service_type_item and service_type_item.item_code:
						# ถ้า Service Type ผูกกับ Item ให้ใช้ Item นั้น
						item_code = service_type_item.item_code
					else:
						# ถ้าไม่ผูกให้ใช้ labor_item จาก settings
						if not settings.labor_item:
							frappe.throw(
								f"ประเภทบริการ '{service_type_row.service_type}' ไม่ได้ผูกกับ Item และยังไม่ได้ตั้งค่า 'รายการสินค้าสำหรับค่าแรง' ใน Truck Service Center Settings",
								title="ยังไม่ได้ตั้งค่า",
							)
						item_code = settings.labor_item

					# สร้าง description สำหรับรายการนี้
					description = service_type_row.service_type
					if service_type_row.repair_position:
						description += f" - {service_type_row.repair_position}"
					if service_type_row.remark:
						description += f" ({service_type_row.remark})"

					si_item = {
						"item_code": item_code,
						"description": description,
						"qty": 1,
						"expense_account": settings.labor_expense_account,
						"cost_center": service_type_item.cost_center
						if service_type_item and service_type_item.cost_center
						else (settings.labor_cost_center or settings.default_cost_center),
						"income_account": service_type_item.income_account
						if service_type_item and service_type_item.income_account
						else settings.default_income_account,
					}

					labor_rate = flt(service_type_row.labor_charges)
					has_discount = (
						flt(service_type_row.discount_percentage) > 0
						or flt(service_type_row.discount_amount) > 0
					)

					if has_discount and labor_rate > 0:
						# ตั้ง price_list_rate = ค่าแรงเต็ม เพื่อให้ SI แสดงส่วนลดได้ถูกต้อง
						si_item["price_list_rate"] = labor_rate
						si_item["discount_percentage"] = flt(service_type_row.discount_percentage)
						si_item["discount_amount"] = flt(service_type_row.discount_amount)
						# rate หลังส่วนลด
						si_item["rate"] = flt(labor_rate - flt(service_type_row.discount_amount), 2)
					else:
						si_item["rate"] = labor_rate

					sales_invoice.append("items", si_item)

		# ถ้าไม่มี service_types แต่มี labor_charges รวม ให้เพิ่มเป็นรายการเดียว (backward compatibility)
		elif flt(self.labor_charges) > 0:
			# ตรวจสอบว่ามีการตั้งค่า Labor Item หรือไม่
			if not settings.labor_item:
				frappe.throw(
					"กรุณาตั้งค่า 'รายการสินค้าสำหรับค่าแรง' ใน Truck Service Center Settings ก่อนสร้าง Sales Invoice",
					title="ยังไม่ได้ตั้งค่า",
				)

			sales_invoice.append(
				"items",
				{
					"item_code": settings.labor_item,
					"qty": 1,
					"rate": flt(self.labor_charges),
					"expense_account": settings.labor_expense_account,
					"cost_center": settings.labor_cost_center or settings.default_cost_center,
					"income_account": settings.default_income_account,
				},
			)

		# ตรวจสอบว่ามีรายการหรือไม่
		if not sales_invoice.items:
			frappe.throw("ไม่สามารถสร้าง Sales Invoice ได้เนื่องจากไม่มีรายการสินค้า")

		# ส่วนลด (ถ้ามี)
		if flt(self.discount_amount) > 0:
			sales_invoice.discount_amount = flt(self.discount_amount)
			sales_invoice.additional_discount_percentage = 0
			sales_invoice.apply_discount_on = "Grand Total"

		# Insert ก่อนโดยยังไม่ใส่ taxes (ป้องกัน ERPNext override ระหว่าง insert)
		sales_invoice.insert()

		# ตั้งค่าเทมเพลตภาษี (taxes_and_charges) จาก Settings หลัง insert
		tax_type = self.tax_type or settings.default_tax_type or "ราคาแยก VAT"
		tax_template = settings.get_tax_template_for_type(tax_type)
		if tax_template:
			sales_invoice.taxes_and_charges = tax_template
			# ล้าง taxes ที่ ERPNext อาจตั้งค่าอัตโนมัติ แล้วใส่จากเทมเพลตของเรา
			sales_invoice.set("taxes", [])
			from erpnext.controllers.accounts_controller import get_taxes_and_charges

			taxes = get_taxes_and_charges("Sales Taxes and Charges Template", tax_template)
			for tax in taxes:
				sales_invoice.append("taxes", tax)

		# คำนวณภาษีและยอดรวมใหม่แล้วบันทึก
		sales_invoice.run_method("calculate_taxes_and_totals")
		sales_invoice.save()

		# Submit อัตโนมัติถ้ามีการตั้งค่า
		if settings.auto_submit_sales_invoice:
			sales_invoice.submit()

		# เก็บ reference
		self.db_set("sales_invoice", sales_invoice.name)

		frappe.msgprint(f"สร้าง Sales Invoice: {sales_invoice.name}")

		return sales_invoice.name


def collect_material_issue_problems(doc):
	"""ตรวจว่าใบเบิกอะไหล่ครบและตรงกับรายการอะไหล่ในใบสั่งงานหรือไม่

	ใช้ร่วมกันระหว่างการกัน submit ฝั่ง server (validate_material_issues_for_submit)
	กับการตรวจล่วงหน้าฝั่ง client (check_material_issues_before_submit) เพื่อไม่ให้
	สองที่ตรวจไม่เหมือนกัน

	Returns:
		dict: ปัญหาแยกตามประเภท — list/dict ว่างแปลว่าไม่มีปัญหา
	"""
	items_without_mi = []
	unsubmitted_mis = {}
	missing_lines = []
	qty_mismatches = []

	for item in doc.service_items:
		if not item.item_code:
			continue

		is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")
		if not is_stock_item:
			continue

		info = {
			"idx": item.idx,
			"item_code": item.item_code,
			"item_name": item.item_name or item.item_code,
			"label": f"{item.item_name or item.item_code} (แถวที่ {item.idx})",
			"material_issue": item.material_issue,
		}

		if not item.material_issue:
			items_without_mi.append(info)
			continue

		docstatus = frappe.db.get_value("Stock Entry", item.material_issue, "docstatus")
		if docstatus != 1:
			status_text = "Draft" if docstatus == 0 else ("Cancelled" if docstatus == 2 else "Unknown")
			unsubmitted_mis.setdefault(item.material_issue, status_text)
			# ยังไม่ submit ก็ยังไม่ต้องเทียบจำนวน จำนวนยังแก้ได้อยู่
			continue

		issued_qty = frappe.db.get_value(
			"Stock Entry Detail",
			{"parent": item.material_issue, "custom_service_order_item": item.name},
			"qty",
		)

		if issued_qty is None:
			# ใบเบิกที่สร้างก่อนแอปมีฟิลด์เชื่อม (หรือ backfill จับคู่ไม่ได้) — ถอยไปเทียบด้วย item_code
			candidates = frappe.get_all(
				"Stock Entry Detail",
				filters={"parent": item.material_issue, "item_code": item.item_code},
				pluck="qty",
			)
			if len(candidates) > 1:
				# มีหลายบรรทัดของสินค้าเดียวกัน แยกไม่ออกว่าบรรทัดไหนเป็นของแถวนี้
				# เดาแล้วฟ้องผิดจะแย่กว่าปล่อยผ่าน จึงข้ามการตรวจจำนวนเฉพาะแถวนี้
				continue
			if not candidates:
				missing_lines.append(info)
				continue
			issued_qty = candidates[0]

		if flt(issued_qty) != flt(item.qty):
			qty_mismatches.append({**info, "ordered": flt(item.qty), "issued": flt(issued_qty)})

	return {
		"items_without_mi": items_without_mi,
		"unsubmitted_mis": unsubmitted_mis,
		"missing_lines": missing_lines,
		"qty_mismatches": qty_mismatches,
	}


@frappe.whitelist()
def check_material_issues_before_submit(service_order):
	"""ตรวจสอบสถานะ Material Issues ก่อน Submit - เรียกจาก client side

	Returns:
		dict: ผลจาก collect_material_issue_problems พร้อม can_submit
	"""
	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("read")

	problems = collect_material_issue_problems(doc)

	return {
		"can_submit": not any(problems.values()),
		**problems,
	}


@frappe.whitelist()
def create_sales_invoice_from_service_order(service_order):
	"""สร้าง Sales Invoice จาก Service Order - สำหรับเรียกจาก client"""
	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("write")
	return doc.create_sales_invoice()


@frappe.whitelist()
def get_item_rate(item_code, customer=None, price_list=None):
	"""ดึงราคาขายและข้อมูลสินค้าสำหรับเติมในแถวอะไหล่ (เรียกจากฟอร์ม)"""
	item_data = frappe.db.get_value("Item", item_code, ["item_name", "description", "stock_uom"], as_dict=1)

	return {
		"rate": get_default_selling_rate(item_code, price_list),
		"item_name": item_data.item_name if item_data else "",
		"description": item_data.description if item_data else "",
		"uom": item_data.stock_uom if item_data else "",
	}


@frappe.whitelist()
def get_item_by_barcode(barcode, customer=None, price_list=None):
	"""ค้นหา Item จากบาร์โค้ดและดึงราคา"""
	if not barcode:
		return None

	# ค้นหา Item จากตาราง Item Barcode
	item_code = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")

	if not item_code:
		# ถ้าไม่เจอใน Item Barcode ให้ลองค้นหาจาก Item.name โดยตรง
		if frappe.db.exists("Item", barcode):
			item_code = barcode
		else:
			return None

	# ดึงข้อมูล Item
	item_data = frappe.db.get_value(
		"Item", item_code, ["item_code", "item_name", "description", "stock_uom"], as_dict=1
	)

	if not item_data:
		return None

	return {
		"item_code": item_data.item_code,
		"item_name": item_data.item_name,
		"description": item_data.description,
		"uom": item_data.stock_uom,
		"rate": get_default_selling_rate(item_code, price_list),
	}


@frappe.whitelist()
def create_material_issue(service_order, item_rows=None):
	"""สร้าง Material Issue สำหรับ items ที่ยังไม่มีใบเบิก (เรียกจากปุ่มในหน้า desk)

	แปลง index ของแถวเป็นตัวแถวจริง แล้วส่งต่อให้ create_material_issue_for_rows
	ตัว index มาจาก dialog ฝั่ง client ที่ยังส่ง index มาเหมือนเดิม

	Args:
		service_order: ชื่อของ Service Order
		item_rows: list ของ row indices ที่ต้องการสร้าง Material Issue (ถ้าไม่ระบุจะสร้างทั้งหมด)
	"""
	import json

	if isinstance(item_rows, str):
		item_rows = json.loads(item_rows)

	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("write")

	if item_rows:
		wanted = {cint(idx) for idx in item_rows}
		rows = [item for idx, item in enumerate(doc.service_items) if idx in wanted]
	else:
		rows = list(doc.service_items)

	return create_material_issue_for_rows(doc, rows)


def create_material_issue_for_rows(doc, rows, ignore_permissions=False):
	"""สร้างใบเบิกอะไหล่จากแถวที่ส่งมาตรง ๆ (ไม่ใช้ index — index เลื่อนได้เมื่อมีการลบแถว)

	ตัวที่ทำงานจริงของทั้งปุ่มในหน้า desk และปุ่มสร้างใบเบิกรายงานในพอร์ทัลช่าง
	ผู้เรียกต้องตรวจสิทธิ์มาก่อนแล้ว — ที่นี่ตรวจเฉพาะกฎทางธุรกิจ (ต้องรับรถก่อน)

	ignore_permissions ส่งต่อไปที่ stock_entry.insert() เพราะ role Technician ไม่มีสิทธิ์
	สร้าง Stock Entry — พอร์ทัลจึงตรวจ gate ของตัวเองให้ครบก่อนแล้วค่อยข้ามสิทธิ์ตรงนี้
	"""
	# ต้องรับรถเข้ามาก่อนจึงจะเบิกอะไหล่ได้
	# ยอมให้ status = In Progress ผ่านด้วย เพราะเอกสารเก่าที่เปลี่ยนสถานะด้วยมือ
	# ก่อนมีกฎนี้จะไม่มี received_date (ของใหม่จะถูก stamp ให้ใน stamp_receive_on_progress)
	if not doc.received_date and doc.status != "In Progress":
		frappe.throw(
			"ยังไม่ได้รับรถเข้าซ่อม กรุณากดปุ่ม “รับรถ” ก่อนสร้างใบเบิกอะไหล่",
			title="ไม่สามารถสร้างใบเบิกอะไหล่ได้",
		)

	# ดึง settings
	settings = frappe.get_single("Truck Service Center Settings")

	# สร้าง Stock Entry
	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.stock_entry_type = "Material Issue"
	stock_entry.company = settings.default_company or frappe.defaults.get_defaults().company
	stock_entry.set_posting_time = 1
	stock_entry.posting_date = frappe.utils.today()
	stock_entry.custom_service_order = doc.name  # Link กลับไป Service Order

	items_added = []

	for item in rows:
		# ข้าม item ที่มี Material Issue แล้ว
		if item.material_issue:
			continue

		# ตรวจสอบว่าเป็น stock item
		is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")
		if not is_stock_item:
			continue

		line = build_material_issue_line(item, settings)
		if not line["s_warehouse"]:
			frappe.msgprint(f"ไม่พบคลังสินค้าสำหรับ {item.item_code}", indicator="orange")
			continue

		stock_entry.append("items", line)
		items_added.append(item)

	if not stock_entry.items:
		frappe.throw("ไม่มีรายการที่สามารถสร้าง Material Issue ได้")

	stock_entry.insert(ignore_permissions=ignore_permissions)

	# อัพเดท Material Issue reference ใน Service Order Items
	for item in items_added:
		item.material_issue = stock_entry.name
		item.material_issue_status = "Draft"

	doc.save(ignore_permissions=ignore_permissions)

	frappe.msgprint(f"สร้าง Material Issue: {stock_entry.name}")

	return stock_entry.name


def get_bay_warnings(doc):
	"""ข้อความเตือนเรื่องช่องจอด — คืนเป็น list ไม่ throw (ผู้ใช้ยืนยันว่าเตือนอย่างเดียว)

	แยกออกมาเป็นฟังก์ชัน pure ระดับ module เพื่อให้ทั้ง validate, endpoint ตรวจก่อนตั้งค่า
	และเทสต์ เรียกใช้ชุดตรรกะเดียวกัน

	สองชั้น:
	1. ช่องจอดหลักถูกใบงานอื่นที่ยังเปิดอยู่ใช้ค้างไว้
	2. งานที่ต้องใช้หลุมซ่อม แต่ช่องจอดที่มีผลจริงกับแถวนั้นไม่มีหลุม
	"""
	warnings = []

	if doc.service_bay:
		filters = {
			"service_bay": doc.service_bay,
			"docstatus": 0,
			"status": ["in", OPEN_STATUSES],
		}
		if not doc.is_new():
			filters["name"] = ["!=", doc.name]

		busy = frappe.get_all("Service Order", filters=filters, pluck="name", limit=5)
		if busy:
			warnings.append(f"ช่องจอด {doc.service_bay} กำลังถูกใช้โดยใบงานที่ยังไม่ปิด: {', '.join(busy)}")

	warnings.extend(_get_pit_warnings(doc))

	return warnings


def _get_pit_warnings(doc):
	"""แถวงานที่ต้องใช้หลุมซ่อม แต่ช่องจอดที่จะได้ใช้จริงไม่มีหลุม

	ดึงข้อมูล master ทีเดียวเป็น batch ทั้ง Service Type และ Service Bay กัน N+1
	ช่องจอดที่มีผลกับแถว = ช่องจอดของแถวเอง ถ้าไม่มีก็ตกไปใช้ช่องจอดหลักของใบงาน
	(ตรงกับที่ apply_default_bay จะเติมให้ตอน save)
	"""
	pairs = []
	for row in doc.service_types:
		bay = row.service_bay or doc.service_bay
		if row.service_type and bay:
			pairs.append((row.service_type, bay))

	if not pairs:
		return []

	service_types = {service_type for service_type, _ in pairs}
	bays = {bay for _, bay in pairs}

	needs_pit = set(
		frappe.get_all(
			"Service Type",
			filters={"name": ["in", list(service_types)], "requires_pit": 1},
			pluck="name",
		)
	)
	if not needs_pit:
		return []

	has_pit = set(
		frappe.get_all(
			"Service Bay",
			filters={"name": ["in", list(bays)], "has_pit": 1},
			pluck="name",
		)
	)

	warnings = []
	seen = set()
	for service_type, bay in pairs:
		if service_type not in needs_pit or bay in has_pit:
			continue
		if (service_type, bay) in seen:
			continue
		seen.add((service_type, bay))
		warnings.append(f"งาน {service_type} ต้องใช้หลุมซ่อม แต่ช่องจอด {bay} ไม่มีหลุม")

	return warnings


@frappe.whitelist()
def check_bay_conflicts(service_order, service_bay=None, row_bays=None):
	"""ตรวจช่องจอดล่วงหน้าก่อนตั้งค่าจริง เพื่อให้ฝั่ง client ขึ้น confirm ได้

	ทับค่าที่กำลังจะตั้งลงบนเอกสารในหน่วยความจำแล้วค่อยตรวจ จะได้เตือนตรงกับผลลัพธ์
	ที่จะเกิดขึ้นจริง ไม่ใช่เตือนจากค่าที่บันทึกไว้เดิม

	row_bays: dict ของ {ชื่อแถว: ช่องจอด} สำหรับกรณีเปลี่ยนช่องจอดรายแถว
	ใช้สิทธิ์ read ก็พอ เพราะไม่ได้เขียนอะไร และไม่ throw — คืน warnings ให้ตัดสินใจต่อ
	"""
	import json

	if isinstance(row_bays, str):
		row_bays = json.loads(row_bays)

	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("read")

	if service_bay is not None:
		doc.service_bay = service_bay or None

	if row_bays:
		rows = {row.name: row for row in doc.service_types}
		for row_name, bay in row_bays.items():
			row = rows.get(row_name)
			if row:
				row.service_bay = bay or None

	return {"warnings": get_bay_warnings(doc)}


def select_requisition_rows(doc, service_row):
	"""อะไหล่ที่ควรอยู่ในใบเบิกของงานรายการหนึ่ง

	จับคู่ด้วย "ค่า" service_type (และ service_package ถ้าแถวงานมี) ไม่ใช่ตัวแถวงาน
	เพราะแถวอะไหล่เก็บแค่ provenance สองฟิลด์นี้ ไม่ได้ link กลับมาที่แถวงานโดยตรง

	ข้อจำกัดที่ตามมา: ถ้าใบงานมีงานประเภทเดียวกัน (+แพ็คเกจเดียวกัน) หลายแถว
	ทุกแถวจะแชร์ pool อะไหล่ก้อนเดียวกัน — ใครกดสร้างใบเบิกก่อนได้ไปทั้งหมด
	แก้จริงต้องเพิ่ม link ระดับแถวลงในแถวอะไหล่ (ยังไม่ทำในรอบนี้)
	"""
	if not service_row.service_type:
		return []

	rows = []
	for item in doc.service_items:
		if item.material_issue:
			continue
		if item.service_type != service_row.service_type:
			continue
		if service_row.service_package and item.service_package != service_row.service_package:
			continue
		rows.append(item)

	return rows


def build_material_issue_line(item, settings):
	"""แปลงแถวอะไหล่ในใบสั่งงานเป็นบรรทัดของ Stock Entry

	ใช้ร่วมกันระหว่างตอนสร้างใบเบิกกับตอนส่งการแก้ไขไปใบเบิก จะได้ไม่ตั้งค่าคนละแบบ
	ผู้เรียกต้องเช็คเองว่า s_warehouse ว่างหรือไม่
	"""
	return {
		"item_code": item.item_code,
		"qty": item.qty,
		"s_warehouse": item.warehouse or settings.default_source_warehouse or settings.default_warehouse,
		"cost_center": item.cost_center or settings.default_cost_center,
		"expense_account": item.expense_account or settings.default_expense_account,
		"basic_rate": item.rate,
		# เก็บ name ของแถวเพื่อ link กลับ — ห้ามใช้ index เพราะเลื่อนได้เมื่อมีการลบแถว
		"custom_service_order_item": item.name,
	}


def get_editable_material_issue(service_order, material_issue):
	"""ดึงใบเบิกที่ยังแก้ไข/ซิงค์ได้ — ต้องเป็น Draft และเป็นของใบสั่งงานนี้"""
	stock_entry = frappe.get_doc("Stock Entry", material_issue)

	if stock_entry.docstatus != 0:
		frappe.throw("สามารถ Sync ได้เฉพาะ Material Issue ที่อยู่ในสถานะ Draft เท่านั้น")

	if stock_entry.get("custom_service_order") != service_order:
		frappe.throw(f"ใบเบิก {material_issue} ไม่ได้เป็นของใบสั่งงาน {service_order}")

	return stock_entry


@frappe.whitelist()
def push_to_material_issue(service_order, material_issue):
	"""แก้ใบเบิก Draft ให้ตรงกับใบสั่งงาน (ทิศทางตรงข้ามกับ sync_material_issue)

	แถวที่ใบเบิกยัง Draft ยังแก้จำนวนได้ พอแก้แล้วใบเบิกไม่ตามจะ submit ใบงานไม่ได้
	(validate_material_issues_for_submit) ฟังก์ชันนี้คือทางแก้ฝั่งตรงข้ามของปุ่ม Sync
	"""
	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("write")
	stock_entry = get_editable_material_issue(service_order, material_issue)
	settings = frappe.get_single("Truck Service Center Settings")

	# เหลือเฉพาะแถวที่ยังชี้มาที่ใบเบิกนี้ — แถวที่ถูกลบหรือย้ายไปใบอื่นจะไม่อยู่ใน dict
	pending_rows = {
		row.name: row for row in doc.service_items if row.material_issue == material_issue and row.name
	}

	changes = []
	kept_lines = []

	for stock_item in stock_entry.items:
		service_item = pending_rows.pop(stock_item.get("custom_service_order_item"), None)

		if not service_item:
			# แถวในใบงานถูกลบไปแล้ว บรรทัดนี้จึงไม่มีเจ้าของ
			changes.append(f"ลบ {stock_item.item_code}")
			continue

		if flt(stock_item.qty) != flt(service_item.qty):
			changes.append(f"{service_item.item_code}: จำนวน {flt(stock_item.qty)} → {flt(service_item.qty)}")
			stock_item.qty = service_item.qty

		if service_item.warehouse and stock_item.s_warehouse != service_item.warehouse:
			changes.append(f"{service_item.item_code}: คลัง → {service_item.warehouse}")
			stock_item.s_warehouse = service_item.warehouse

		kept_lines.append(stock_item)

	# แถวที่ยังผูกกับใบเบิกนี้แต่บรรทัดหายไป (เช่นถูกลบออกจากใบเบิกด้วยมือ) → เพิ่มกลับ
	new_lines = []
	for service_item in pending_rows.values():
		line = build_material_issue_line(service_item, settings)
		if not line["s_warehouse"]:
			frappe.msgprint(f"ไม่พบคลังสินค้าสำหรับ {service_item.item_code}", indicator="orange")
			continue
		new_lines.append(line)
		changes.append(f"เพิ่ม {service_item.item_code}")

	if not changes:
		frappe.msgprint("ใบเบิกตรงกับใบสั่งงานอยู่แล้ว ไม่มีอะไรต้องแก้")
		return True

	if not kept_lines and not new_lines:
		frappe.throw(
			f"การแก้ตามใบสั่งงานจะทำให้ใบเบิก {material_issue} ไม่เหลือรายการเลย<br>กรุณายกเลิกหรือลบใบเบิกนี้แทน",
			title="แก้ใบเบิกไม่ได้",
		)

	stock_entry.items = kept_lines
	for idx, line in enumerate(kept_lines, start=1):
		line.idx = idx
	for line in new_lines:
		stock_entry.append("items", line)

	stock_entry.save()

	frappe.msgprint(
		f"แก้ใบเบิก {material_issue} ตามใบสั่งงานเรียบร้อย:<br>" + "<br>".join(f"• {change}" for change in changes)
	)

	return True


@frappe.whitelist()
def sync_material_issue(service_order, material_issue):
	"""ซิงค์ข้อมูลจาก Material Issue กลับมายัง Service Order

	Args:
		service_order: ชื่อของ Service Order
		material_issue: ชื่อของ Stock Entry (Material Issue)
	"""
	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("write")
	stock_entry = get_editable_material_issue(service_order, material_issue)

	# จับคู่ด้วย name ของแถว ไม่ใช่ลำดับ — ลำดับเลื่อนได้ถ้ามีการลบแถวหลังสร้างใบเบิก
	rows_by_name = {row.name: row for row in doc.service_items}
	updated_items = []

	for stock_item in stock_entry.items:
		service_item = rows_by_name.get(stock_item.get("custom_service_order_item"))
		if not service_item:
			continue

		# ซิงค์เฉพาะจำนวนกับคลัง — ห้ามดึง basic_rate กลับมาเป็น rate เด็ดขาด
		# ERPNext เขียนทับ basic_rate ของบรรทัดที่มี s_warehouse ด้วยราคาทุนทุกครั้งที่ save
		# (set_rate_for_outgoing_items) ดึงกลับมาจะกลายเป็นขายเท่าทุน
		service_item.qty = stock_item.qty
		service_item.warehouse = stock_item.s_warehouse

		updated_items.append(service_item.item_code)

	if not updated_items:
		# ใบเบิกที่สร้างก่อนแอปมีฟิลด์เชื่อมจะไม่มี custom_service_order_item ให้จับคู่
		frappe.throw(
			f"ไม่สามารถจับคู่รายการในใบเบิก {material_issue} กับใบสั่งงานได้<br>"
			"ใบเบิกนี้อาจถูกสร้างก่อนระบบมีฟิลด์เชื่อมรายการ กรุณาลบใบเบิกแล้วสร้างใหม่",
			title="Sync ไม่สำเร็จ",
		)

	doc.save()

	frappe.msgprint(f"Sync ข้อมูลจาก Material Issue เรียบร้อย: {', '.join(updated_items)}")

	return True


@frappe.whitelist()
def get_service_type_items(service_type):
	"""ดึงรายการอะไหล่ที่ผูกไว้กับ Service Type

	Args:
		service_type: ชื่อ Service Type

	Returns:
		list: รายการอะไหล่พร้อมรายละเอียด
	"""
	doc = frappe.get_doc("Service Type", service_type)
	doc.check_permission("read")

	items = []
	if doc.items:
		for item in doc.items:
			items.append(
				{
					"item_code": item.item_code,
					"item_name": item.item_name,
					"description": item.description,
					"qty": item.qty,
					"uom": item.uom,
					"rate": item.rate,
					"amount": item.amount,
				}
			)

	return items


@frappe.whitelist()
def get_material_issue_summary(service_order):
	"""ดึงสรุปข้อมูล Material Issues ทั้งหมดของ Service Order

	Returns:
		dict: สถิติและรายการ Material Issues
	"""
	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("read")

	# รวบรวม Material Issues ทั้งหมด
	material_issues = {}

	for item in doc.service_items:
		if item.material_issue:
			if item.material_issue not in material_issues:
				# ดึงข้อมูล Stock Entry
				stock_entry = frappe.db.get_value(
					"Stock Entry",
					item.material_issue,
					["name", "docstatus", "posting_date", "total_amount"],
					as_dict=1,
				)

				if stock_entry:
					status_map = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
					material_issues[item.material_issue] = {
						"name": stock_entry.name,
						"status": status_map.get(stock_entry.docstatus, "Unknown"),
						"posting_date": stock_entry.posting_date,
						"total_amount": stock_entry.total_amount,
						"item_count": 0,
					}

			# นับจำนวน items
			if item.material_issue in material_issues:
				material_issues[item.material_issue]["item_count"] += 1

	return {"total_count": len(material_issues), "material_issues": list(material_issues.values())}


@frappe.whitelist()
def get_party_shipping_address(doctype, name):
	"""Wrapper for erpnext get_party_shipping_address"""
	from erpnext.accounts.party import get_party_shipping_address as _get_party_shipping_address

	return _get_party_shipping_address(doctype, name)


@frappe.whitelist()
def receive_vehicle(service_order):
	"""รับรถ — stamp user, เวลา, เปลี่ยนสถานะเป็น In Progress"""
	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("write")

	if doc.docstatus != 0:
		frappe.throw("ไม่สามารถรับรถได้ เอกสารถูก submit หรือ cancel แล้ว")

	if doc.status != "Draft":
		frappe.throw("ไม่สามารถรับรถได้ สถานะปัจจุบันไม่ใช่ Draft")

	if not doc.fuel_level_in:
		frappe.throw("กรุณาบันทึกสถานะน้ำมันรับเข้าก่อนทำการรับรถ")

	doc.received_by = frappe.session.user
	doc.received_date = now_datetime()
	doc.status = "In Progress"
	doc.save()

	return {"status": "ok"}


@frappe.whitelist()
def create_payment_entry(service_order):
	"""สร้าง Payment Entry (draft) รับชำระเงินจาก Sales Invoice ของ Service Order

	ใช้ helper มาตรฐานของ ERPNext (get_payment_entry) เพื่อให้ allocation/บัญชีถูกต้อง
	ผู้ใช้ตรวจสอบและ Submit ที่หน้า Payment Entry เอง — เมื่อ Submit แล้ว
	สถานะการชำระเงินของ Service Order จะถูกซิงค์กลับผ่าน doc_events (ดู hooks.py)
	"""
	doc = frappe.get_doc("Service Order", service_order)
	doc.check_permission("read")

	if not doc.sales_invoice:
		frappe.throw("กรุณาสร้าง Sales Invoice ก่อนรับชำระเงิน")

	si_docstatus, si_outstanding = frappe.db.get_value(
		"Sales Invoice", doc.sales_invoice, ["docstatus", "outstanding_amount"]
	)
	if si_docstatus != 1:
		frappe.throw(f"Sales Invoice {doc.sales_invoice} ยังไม่ได้ Submit หรือถูกยกเลิกแล้ว")
	if flt(si_outstanding) <= 0:
		frappe.throw("ใบแจ้งหนี้นี้ชำระครบแล้ว")

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	payment_entry = get_payment_entry("Sales Invoice", doc.sales_invoice)

	# จับคู่วิธีชำระเงินของใบสั่งงานกับ Mode of Payment ของ ERPNext (ถ้ามี)
	mode_alias = {"Bank Transfer": "Wire Transfer"}
	mode = mode_alias.get(doc.payment_method, doc.payment_method)
	if mode and frappe.db.exists("Mode of Payment", mode):
		payment_entry.mode_of_payment = mode

	# ภาษีหัก ณ ที่จ่าย: ลูกค้าจ่ายน้อยลงตามยอดที่หัก แต่ปิดหนี้ใบแจ้งหนี้เต็มจำนวน
	# โดยส่วนต่างลงบัญชีสินทรัพย์ "ภาษีถูกหัก ณ ที่จ่าย" ผ่าน deductions
	if doc.apply_wht and flt(doc.wht_amount) > 0:
		si_totals = frappe.db.get_value(
			"Sales Invoice", doc.sales_invoice, ["grand_total", "rounded_total"], as_dict=1
		)
		# เทียบกับฐานเดียวกับที่ ERPNext ใช้คิดยอดค้าง (rounded_total ถ้ามีการปัดเศษ)
		si_grand_total = flt(si_totals.rounded_total) or flt(si_totals.grand_total)

		if flt(si_outstanding) < si_grand_total:
			# มีการชำระบางส่วนไปก่อนแล้ว — เดายอดหักที่เหลือไม่ได้ ให้ผู้ใช้ใส่ deduction เอง
			frappe.msgprint(
				"ใบแจ้งหนี้นี้มีการชำระบางส่วนแล้ว ระบบไม่ใส่รายการภาษีหัก ณ ที่จ่ายให้อัตโนมัติ "
				"กรุณาตรวจสอบและเพิ่มรายการหัก (Deductions) ใน Payment Entry เอง",
				indicator="orange",
				title="ภาษีหัก ณ ที่จ่าย",
			)
		else:
			settings = frappe.get_single("Truck Service Center Settings")
			if not settings.wht_account:
				frappe.throw(
					"กรุณาตั้งค่า 'บัญชีภาษีถูกหัก ณ ที่จ่าย' ใน Truck Service Center Settings "
					"ก่อนรับชำระเงินที่มีภาษีหัก ณ ที่จ่าย",
					title="ยังไม่ได้ตั้งค่า",
				)

			cost_center = settings.default_cost_center or settings.labor_cost_center
			if not cost_center:
				frappe.throw(
					"กรุณาตั้งค่า 'ศูนย์ต้นทุนเริ่มต้น' ใน Truck Service Center Settings "
					"(จำเป็นสำหรับรายการหักภาษี ณ ที่จ่ายใน Payment Entry)",
					title="ยังไม่ได้ตั้งค่า",
				)

			received = flt(flt(si_outstanding) - flt(doc.wht_amount), 2)
			payment_entry.paid_amount = received
			payment_entry.received_amount = received
			payment_entry.append(
				"deductions",
				{
					"account": settings.wht_account,
					"cost_center": cost_center,
					"amount": flt(doc.wht_amount),
					"description": f"ภาษีหัก ณ ที่จ่าย {flt(doc.wht_rate)}% ({doc.name})",
				},
			)

	payment_entry.insert()

	frappe.msgprint(f"สร้าง Payment Entry: {payment_entry.name}")

	return payment_entry.name


def sync_payment_from_sales_invoice(sales_invoice):
	"""ซิงค์ยอดชำระจาก Sales Invoice กลับมายัง Service Order ที่ผูกกัน

	paid_amount = grand_total - outstanding ของใบแจ้งหนี้ (ยอดที่ตัดหนี้จริงในบัญชี
	ไม่ว่าจะชำระผ่าน Payment Entry, Journal Entry หรือ POS)
	"""
	so_names = frappe.get_all("Service Order", filters={"sales_invoice": sales_invoice}, pluck="name")
	if not so_names:
		return

	si = frappe.db.get_value(
		"Sales Invoice",
		sales_invoice,
		["grand_total", "rounded_total", "outstanding_amount", "docstatus"],
		as_dict=1,
	)
	if not si:
		return

	# ERPNext คิดยอดค้างจาก rounded_total (ถ้าเปิดการปัดเศษ) — ต้องใช้ฐานเดียวกัน
	# ไม่งั้นเศษปัด (เช่น 3370.50 → 3370) จะกลายเป็น "ชำระแล้ว 0.50" ทั้งที่ยังไม่จ่าย
	invoice_total = flt(si.rounded_total) or flt(si.grand_total)

	for so_name in so_names:
		total_amount = flt(frappe.db.get_value("Service Order", so_name, "total_amount"))

		# ใบแจ้งหนี้ถูกยกเลิก/ยัง draft → ถือว่ายังไม่มีการชำระ
		paid = invoice_total - flt(si.outstanding_amount) if si.docstatus == 1 else 0

		if paid <= 0:
			payment_status, paid = "Unpaid", 0
		elif flt(si.outstanding_amount) <= 0:
			payment_status = "Paid"
		else:
			payment_status = "Partially Paid"

		# ยอดค้างมองจากฝั่ง Service Order (กันเศษปัดจากภาษีของใบแจ้งหนี้)
		outstanding = 0 if payment_status == "Paid" else max(total_amount - paid, 0)

		frappe.db.set_value(
			"Service Order",
			so_name,
			{
				"paid_amount": paid,
				"outstanding_amount": outstanding,
				"payment_status": payment_status,
			},
		)


def on_payment_entry_change(doc, method=None):
	"""doc_events hook: Payment Entry submit/cancel → ซิงค์สถานะชำระเงินของ Service Order"""
	for ref in doc.references or []:
		if ref.reference_doctype == "Sales Invoice":
			sync_payment_from_sales_invoice(ref.reference_name)


def on_journal_entry_change(doc, method=None):
	"""doc_events hook: Journal Entry submit/cancel → ซิงค์สถานะชำระเงินของ Service Order"""
	seen = set()
	for acc in doc.accounts or []:
		if acc.reference_type == "Sales Invoice" and acc.reference_name and acc.reference_name not in seen:
			seen.add(acc.reference_name)
			sync_payment_from_sales_invoice(acc.reference_name)


def on_sales_invoice_change(doc, method=None):
	"""doc_events hook: Sales Invoice submit/cancel → ซิงค์สถานะชำระเงินของ Service Order"""
	sync_payment_from_sales_invoice(doc.name)


MATERIAL_ISSUE_STATUS_BY_DOCSTATUS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


def sync_material_issue_status(material_issue, docstatus=None):
	"""เขียนสถานะใบเบิกอะไหล่ลง Service Order Item ที่ผูกอยู่ (ลง DB จริง ไม่ใช่แค่หน้าจอ)

	ใบเบิกถูกยกเลิก → ปลด link ทิ้งด้วย เพื่อให้แถวนั้นกลับไปเป็น "ยังไม่มีใบเบิก"
	เบิกใหม่ได้ (create_material_issue ข้ามแถวที่มี material_issue ทุกกรณี) และไม่ค้าง
	validate_material_issues_for_submit ที่ต้องการใบเบิกสถานะ submitted
	"""
	rows = frappe.get_all(
		"Service Order Item",
		filters={"material_issue": material_issue},
		fields=["name", "parent"],
	)
	if not rows:
		return

	if docstatus is None:
		docstatus = frappe.db.get_value("Stock Entry", material_issue, "docstatus")

	if cint(docstatus) == 2:
		values = {"material_issue": None, "material_issue_status": None}
	else:
		values = {"material_issue_status": MATERIAL_ISSUE_STATUS_BY_DOCSTATUS.get(cint(docstatus))}

	for row in rows:
		frappe.db.set_value("Service Order Item", row.name, values, update_modified=False)
		# set_value ล้าง cache ให้เฉพาะ doctype ที่เขียน — เอกสารแม่ที่ get_cached_doc
		# ใช้อยู่ยังถือแถวลูกเวอร์ชันเก่า ต้องล้างเอง
		frappe.clear_document_cache("Service Order", row.parent)


def on_stock_entry_change(doc, method=None):
	"""doc_events hook: Material Issue submit/cancel → ซิงค์สถานะกลับ Service Order

	on_cancel ทำงานก่อน check_no_back_links_exist() การปลด link ที่นี่จึงทำให้
	ยกเลิกใบเบิกของใบงานที่ submit แล้วได้ (เดิมติด LinkExistsError)
	"""
	if doc.purpose != "Material Issue":
		return

	sync_material_issue_status(doc.name, doc.docstatus)

# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase


def make_appointment(package_rows=None, service_rows=None):
	"""สร้าง Service Appointment ในหน่วยความจำ (ไม่ insert) แบบเดียวกับ test_service_order

	ไม่ insert เพราะ fetch_from จะทับ repair_time_hours จาก Service Package master
	ตอน save และเทสต์ชุดนี้ต้องการคุมค่าของแถวเอง
	"""
	appointment = frappe.new_doc("Service Appointment")

	for row in package_rows or []:
		appointment.append("service_packages", row)
	for row in service_rows or []:
		appointment.append("service_types", row)

	return appointment


class UnitTestServiceAppointment(UnitTestCase):
	"""ทดสอบสูตรระยะเวลานัดหมาย: เวลาซ่อมจริงของแพ็คเกจ vs ผลรวมเวลาของงาน"""

	def test_package_repair_time_wins_over_row_sum(self):
		"""แพ็คเกจที่กรอกเวลาซ่อมจริงไว้ ใช้ค่านั้นแทนผลรวมเวลาของงานในแพ็คเกจ

		เพราะงานในแพ็คเกจทำขนานกันได้ ผลรวมจึงยาวเกินเวลาที่รถอยู่ในศูนย์จริง
		"""
		appointment = make_appointment(
			package_rows=[{"service_package": "PKG-1", "repair_time_hours": 2}],
			service_rows=[
				{"service_package": "PKG-1", "estimated_time": 1.5},
				{"service_package": "PKG-1", "estimated_time": 2.5},
			],
		)

		appointment.calculate_estimated_duration()

		self.assertEqual(appointment.estimated_duration, 2)

	def test_falls_back_to_row_sum_when_repair_time_blank(self):
		"""แพ็คเกจที่ยังไม่กรอกเวลาซ่อมจริง ถอยไปใช้ผลรวมเวลาของงานในแพ็คเกจตามเดิม"""
		appointment = make_appointment(
			package_rows=[{"service_package": "PKG-1"}],
			service_rows=[
				{"service_package": "PKG-1", "estimated_time": 1.5},
				{"service_package": "PKG-1", "estimated_time": 2.5},
			],
		)

		appointment.calculate_estimated_duration()

		self.assertEqual(appointment.estimated_duration, 4)

	def test_loose_service_rows_are_added_once(self):
		"""งานที่ไม่ได้มาจากแพ็คเกจ บวกเพิ่มจากเวลาซ่อมจริงของแพ็คเกจ"""
		appointment = make_appointment(
			package_rows=[{"service_package": "PKG-1", "repair_time_hours": 2}],
			service_rows=[
				{"service_package": "PKG-1", "estimated_time": 3},
				{"estimated_time": 1.25},
			],
		)

		appointment.calculate_estimated_duration()

		self.assertEqual(appointment.estimated_duration, 3.25)

	def test_two_packages_do_not_share_rows(self):
		"""แพ็คเกจหลายตัวต้องไม่ดึงเวลาของกันและกัน (.pop กันนับซ้ำ)"""
		appointment = make_appointment(
			package_rows=[
				{"service_package": "PKG-1", "repair_time_hours": 2},
				{"service_package": "PKG-2"},
			],
			service_rows=[
				{"service_package": "PKG-1", "estimated_time": 5},
				{"service_package": "PKG-2", "estimated_time": 1.5},
			],
		)

		appointment.calculate_estimated_duration()

		# PKG-1 ใช้เวลาซ่อมจริง 2 + PKG-2 ถอยไปใช้ผลรวม 1.5
		self.assertEqual(appointment.estimated_duration, 3.5)

	def test_package_row_without_service_rows(self):
		"""แถวงานของแพ็คเกจถูกลบไปหมดแล้ว ต้องไม่พัง — เวลาซ่อมจริงยังนับให้"""
		appointment = make_appointment(
			package_rows=[{"service_package": "PKG-1", "repair_time_hours": 2}],
			service_rows=[],
		)

		appointment.calculate_estimated_duration()

		self.assertEqual(appointment.estimated_duration, 2)

	def test_orphan_service_rows_still_counted(self):
		"""แถวงานที่แพ็คเกจต้นทางถูกลบไปแล้ว ยังต้องนับเวลาให้ ไม่ใช่หายไปเฉย ๆ"""
		appointment = make_appointment(
			package_rows=[],
			service_rows=[{"service_package": "PKG-GONE", "estimated_time": 1.75}],
		)

		appointment.calculate_estimated_duration()

		self.assertEqual(appointment.estimated_duration, 1.75)

	def test_empty_appointment_is_zero(self):
		"""ยังไม่มีงานและแพ็คเกจ → 0 ไม่ใช่ None"""
		appointment = make_appointment()

		appointment.calculate_estimated_duration()

		self.assertEqual(appointment.estimated_duration, 0)

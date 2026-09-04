# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.truck_service_center.doctype.service_appointment.service_appointment import (
	CAP_SOURCE_HALF_DAY,
	CAP_SOURCE_NORMAL,
	CAP_SOURCE_OVERRIDE,
	CAP_SOURCE_WEEKLY_HOLIDAY,
	STATUS_CLOSED,
	STATUS_FREE,
	STATUS_FULL,
	STATUS_NEAR_FULL,
	WORK_TYPE_GENERAL,
	WORK_TYPE_PIT,
	availability_status,
	build_capacity_warnings,
	compute_allocation,
	resolve_bay_caps,
	split_pit_hours,
)


def make_appointment(package_rows=None, service_rows=None, bay_rows=None):
	"""สร้าง Service Appointment ในหน่วยความจำ (ไม่ insert) แบบเดียวกับ test_service_order

	ไม่ insert เพราะ fetch_from จะทับ repair_time_hours จาก Service Package master
	ตอน save และเทสต์ชุดนี้ต้องการคุมค่าของแถวเอง
	"""
	appointment = frappe.new_doc("Service Appointment")

	for row in package_rows or []:
		appointment.append("service_packages", row)
	for row in service_rows or []:
		appointment.append("service_types", row)
	for row in bay_rows or []:
		appointment.append("bay_allocations", row)

	return appointment


def make_bay(bay, cap=8.0, booked=0.0, has_pit=0, is_closed=False):
	"""แถว availability ประดิษฐ์ — รูปเดียวกับที่ get_bay_availability คืนให้"""
	return {
		"bay": bay,
		"bay_name": bay,
		"has_pit": has_pit,
		"cap": cap,
		"booked": booked,
		"free": cap - booked,
		"is_closed": is_closed,
		"status": availability_status(cap, booked, is_closed),
	}


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


class UnitTestSplitPitHours(UnitTestCase):
	"""ทดสอบการแยกชั่วโมงงานหลุมกับงานทั่วไป (ส่ง pit set เข้าไปตรง ๆ ไม่แตะฐานข้อมูล)"""

	def test_loose_rows_split_by_flag(self):
		"""แถวเดี่ยวที่ไม่ได้มาจากแพ็คเกจ แยกตามธงต้องใช้หลุมของแต่ละงาน"""
		appointment = make_appointment(
			service_rows=[
				{"service_type": "เปลี่ยนน้ำมันเครื่อง", "estimated_time": 2},
				{"service_type": "เปลี่ยนแบตเตอรี่", "estimated_time": 1.5},
			],
		)

		pit_hours, general_hours = split_pit_hours(appointment, {"เปลี่ยนน้ำมันเครื่อง"})

		self.assertEqual(pit_hours, 2)
		self.assertEqual(general_hours, 1.5)

	def test_package_splits_by_effective_hours(self):
		"""แพ็คเกจปกติ: เวลาซ่อมจริงเป็นเพดาน ส่วนที่เหลือคืองานทั่วไป"""
		appointment = make_appointment(
			package_rows=[{"service_package": "PKG-1", "repair_time_hours": 4}],
			service_rows=[
				{"service_package": "PKG-1", "service_type": "เปลี่ยนน้ำมันเครื่อง", "estimated_time": 1},
				{"service_package": "PKG-1", "service_type": "ล้างอัดฉีด", "estimated_time": 2},
			],
		)

		pit_hours, general_hours = split_pit_hours(appointment, {"เปลี่ยนน้ำมันเครื่อง"})

		self.assertEqual(pit_hours, 1)
		self.assertEqual(general_hours, 3)

	def test_pit_rows_are_capped_by_package_repair_time(self):
		"""แถวหลุมรวมเกินเวลาซ่อมจริงของแพ็คเกจ → หลุมได้แค่เวลาซ่อมจริง งานทั่วไปเหลือ 0

		ผลรวมของสองค่าต้องเท่ากับ estimated_duration เสมอ ไม่งั้นจะขึ้นคำเตือน stale ทันที
		"""
		appointment = make_appointment(
			package_rows=[{"service_package": "PKG-1", "repair_time_hours": 2}],
			service_rows=[
				{"service_package": "PKG-1", "service_type": "เปลี่ยนน้ำมันเครื่อง", "estimated_time": 3},
				{"service_package": "PKG-1", "service_type": "เปลี่ยนน้ำมันเกียร์", "estimated_time": 2},
			],
		)

		pit_hours, general_hours = split_pit_hours(appointment, {"เปลี่ยนน้ำมันเครื่อง", "เปลี่ยนน้ำมันเกียร์"})

		appointment.calculate_estimated_duration()
		self.assertEqual(pit_hours, 2)
		self.assertEqual(general_hours, 0)
		self.assertEqual(pit_hours + general_hours, appointment.estimated_duration)

	def test_falls_back_to_row_sum_when_repair_time_blank(self):
		"""แพ็คเกจที่ยังไม่กรอกเวลาซ่อมจริง ถอยไปใช้ผลรวมเวลาของแถวตามสูตรระยะเวลา"""
		appointment = make_appointment(
			package_rows=[{"service_package": "PKG-1"}],
			service_rows=[
				{"service_package": "PKG-1", "service_type": "เปลี่ยนน้ำมันเครื่อง", "estimated_time": 1.5},
				{"service_package": "PKG-1", "service_type": "ล้างอัดฉีด", "estimated_time": 2.5},
			],
		)

		pit_hours, general_hours = split_pit_hours(appointment, {"เปลี่ยนน้ำมันเครื่อง"})

		self.assertEqual(pit_hours, 1.5)
		self.assertEqual(general_hours, 2.5)

	def test_orphan_rows_are_split_by_flag(self):
		"""แถวงานที่แพ็คเกจต้นทางถูกลบไปแล้ว ยังต้องถูกนับและแยกตามธงหลุม"""
		appointment = make_appointment(
			service_rows=[
				{"service_package": "PKG-GONE", "service_type": "เปลี่ยนน้ำมันเครื่อง", "estimated_time": 1.25},
				{"service_package": "PKG-GONE", "service_type": "ล้างอัดฉีด", "estimated_time": 0.75},
			],
		)

		pit_hours, general_hours = split_pit_hours(appointment, {"เปลี่ยนน้ำมันเครื่อง"})

		self.assertEqual(pit_hours, 1.25)
		self.assertEqual(general_hours, 0.75)

	def test_empty_appointment_is_zero(self):
		"""ยังไม่มีงานและแพ็คเกจ → (0, 0) ไม่ใช่ None"""
		self.assertEqual(split_pit_hours(make_appointment(), set()), (0, 0))


class UnitTestComputeAllocation(UnitTestCase):
	"""ทดสอบการจัดช่องจอด (availability ประดิษฐ์ ไม่แตะฐานข้อมูล)"""

	def test_pit_work_goes_to_emptiest_pit_bay(self):
		"""งานหลุมลงช่องที่มีหลุมและว่างที่สุด"""
		availability = [
			make_bay("BAY-01", has_pit=1, booked=6),
			make_bay("BAY-02", has_pit=1, booked=2),
			make_bay("BAY-03"),
		]

		allocations, warnings = compute_allocation(3, 0, availability)

		self.assertEqual(warnings, [])
		self.assertEqual(
			allocations,
			[{"service_bay": "BAY-02", "work_type": WORK_TYPE_PIT, "allocated_hours": 3}],
		)

	def test_general_work_prefers_non_pit_bay_when_both_fit(self):
		"""งานทั่วไปเลือกช่องที่ไม่มีหลุม แม้ช่องหลุมจะว่างกว่า — กันหลุมไว้ให้งานที่ต้องใช้"""
		availability = [
			make_bay("BAY-01", has_pit=1, booked=0),
			make_bay("BAY-02", booked=3),
		]

		allocations, _warnings = compute_allocation(0, 2, availability)

		self.assertEqual(allocations[0]["service_bay"], "BAY-02")
		self.assertEqual(allocations[0]["work_type"], WORK_TYPE_GENERAL)

	def test_pit_bay_takes_general_work_when_it_is_the_only_fit(self):
		"""ช่องที่รับไหวมาก่อนเรื่องหลุม — ช่องหลุมรับงานทั่วไปได้ถ้าเป็นช่องเดียวที่พอ"""
		availability = [
			make_bay("BAY-01", has_pit=1, booked=0),
			make_bay("BAY-02", booked=7),
		]

		allocations, _warnings = compute_allocation(0, 5, availability)

		self.assertEqual(allocations[0]["service_bay"], "BAY-01")

	def test_single_pit_bay_takes_both_parts(self):
		"""มีช่องเดียวและเป็นช่องหลุม → รับทั้งสองส่วนเป็นสองแถว และหักชั่วโมงต่อเนื่องกัน"""
		availability = [make_bay("BAY-01", has_pit=1)]

		allocations, warnings = compute_allocation(2, 3, availability)

		self.assertEqual(warnings, [])
		self.assertEqual([row["service_bay"] for row in allocations], ["BAY-01", "BAY-01"])
		self.assertEqual([row["work_type"] for row in allocations], [WORK_TYPE_PIT, WORK_TYPE_GENERAL])
		self.assertEqual([row["allocated_hours"] for row in allocations], [2, 3])

	def test_pit_work_without_pit_bay_merges_into_general(self):
		"""ไม่มีช่องหลุมเปิดอยู่ → รวมชั่วโมงหลุมเข้ากับงานทั่วไปแล้วเตือน"""
		availability = [make_bay("BAY-01"), make_bay("BAY-02")]

		allocations, warnings = compute_allocation(2, 1, availability)

		self.assertEqual(len(allocations), 1)
		self.assertEqual(allocations[0]["work_type"], WORK_TYPE_GENERAL)
		self.assertEqual(allocations[0]["allocated_hours"], 3)
		self.assertEqual(len(warnings), 1)
		self.assertIn("หลุมซ่อม", warnings[0])

	def test_no_bay_fits_still_allocates_emptiest(self):
		"""ไม่มีช่องไหนรับไหว ยังต้องจัดลงช่องที่ว่างที่สุด ไม่ throw (OT เป็นเรื่องของคำเตือน)"""
		availability = [
			make_bay("BAY-01", booked=7),
			make_bay("BAY-02", booked=5),
		]

		allocations, warnings = compute_allocation(0, 10, availability)

		self.assertEqual(warnings, [])
		self.assertEqual(allocations[0]["service_bay"], "BAY-02")
		self.assertEqual(allocations[0]["allocated_hours"], 10)

	def test_zero_hour_part_creates_no_row(self):
		"""ส่วนที่เป็น 0 ชม. ไม่สร้างแถว"""
		availability = [make_bay("BAY-01", has_pit=1)]

		allocations, _warnings = compute_allocation(0, 0, availability)

		self.assertEqual(allocations, [])

	def test_no_bays_at_all_allocates_nothing(self):
		"""ไม่มีช่องจอดเลย → ไม่มีแถว และไม่ throw"""
		self.assertEqual(compute_allocation(2, 2, []), ([], []))


class UnitTestResolveBayCaps(UnitTestCase):
	"""ทดสอบลำดับความสำคัญของชั่วโมงรับงานรายวัน"""

	def setUp(self):
		self.bays = [
			{"name": "BAY-01", "daily_capacity_hours": 8},
			{"name": "BAY-02", "daily_capacity_hours": 6},
		]

	def test_weekly_holiday_closes_every_bay(self):
		"""วันหยุดประจำสัปดาห์ → ตัวคูณ 0 ทุกช่องปิด"""
		caps = resolve_bay_caps(self.bays, "หยุด", [])

		self.assertEqual(caps["BAY-01"]["cap"], 0)
		self.assertTrue(caps["BAY-01"]["is_closed"])
		self.assertEqual(caps["BAY-01"]["source"], CAP_SOURCE_WEEKLY_HOLIDAY)

	def test_half_day_halves_each_bay_capacity(self):
		"""ครึ่งวัน = ครึ่งหนึ่งของชั่วโมงรับงานของแต่ละช่อง (8 → 4, 6 → 3)"""
		caps = resolve_bay_caps(self.bays, "ครึ่งวัน", [])

		self.assertEqual(caps["BAY-01"]["cap"], 4)
		self.assertEqual(caps["BAY-02"]["cap"], 3)
		self.assertEqual(caps["BAY-01"]["source"], CAP_SOURCE_HALF_DAY)
		self.assertFalse(caps["BAY-01"]["is_closed"])

	def test_unknown_day_mode_counts_as_full_day(self):
		"""โหมดว่างหรือไม่รู้จัก → เต็มวัน กัน site ที่ยังไม่ได้ seed กลายเป็นปิดทั้งสัปดาห์"""
		for day_mode in (None, "", "ไม่รู้จัก"):
			caps = resolve_bay_caps(self.bays, day_mode, [])

			self.assertEqual(caps["BAY-01"]["cap"], 8)
			self.assertEqual(caps["BAY-01"]["source"], CAP_SOURCE_NORMAL)

	def test_global_override_beats_weekly_setting(self):
		"""override ที่เว้นช่องจอดว่าง มีผลทุกช่องและชนะการตั้งค่าประจำสัปดาห์"""
		caps = resolve_bay_caps(self.bays, "ครึ่งวัน", [{"service_bay": None, "capacity_hours": 5}])

		self.assertEqual(caps["BAY-01"]["cap"], 5)
		self.assertEqual(caps["BAY-02"]["cap"], 5)
		self.assertEqual(caps["BAY-01"]["source"], CAP_SOURCE_OVERRIDE)

	def test_bay_override_beats_global_override(self):
		"""override ที่ระบุช่องจอด ชนะ override ที่มีผลทุกช่อง"""
		overrides = [
			{"service_bay": None, "capacity_hours": 5},
			{"service_bay": "BAY-01", "capacity_hours": 2},
		]

		caps = resolve_bay_caps(self.bays, "เต็มวัน", overrides)

		self.assertEqual(caps["BAY-01"]["cap"], 2)
		self.assertEqual(caps["BAY-02"]["cap"], 5)

	def test_override_can_open_a_weekly_holiday(self):
		"""override > 0 บนวันหยุดประจำสัปดาห์ = เปิดทำการวันนั้น"""
		caps = resolve_bay_caps(self.bays, "หยุด", [{"service_bay": None, "capacity_hours": 4}])

		self.assertEqual(caps["BAY-01"]["cap"], 4)
		self.assertFalse(caps["BAY-01"]["is_closed"])

	def test_override_zero_closes_a_working_day_with_reason(self):
		"""override 0 ปิดวันทำการได้ และเหตุผลต้องติดมาให้เอาไปแสดง"""
		overrides = [{"service_bay": "BAY-01", "capacity_hours": 0, "reason": "อบรมประจำปี"}]

		caps = resolve_bay_caps(self.bays, "เต็มวัน", overrides)

		self.assertTrue(caps["BAY-01"]["is_closed"])
		self.assertEqual(caps["BAY-01"]["reason"], "อบรมประจำปี")
		self.assertEqual(caps["BAY-02"]["cap"], 6)


class UnitTestAvailabilityStatus(UnitTestCase):
	"""ทดสอบเกณฑ์ badge สถานะช่องจอด"""

	def test_empty_and_below_threshold_is_free(self):
		"""ยังไม่ถึง 80% ถือว่าว่าง"""
		self.assertEqual(availability_status(10, 0), STATUS_FREE)
		self.assertEqual(availability_status(10, 7.99), STATUS_FREE)

	def test_eighty_percent_is_near_full(self):
		"""ตั้งแต่ 80% ขึ้นไปคือใกล้เต็ม"""
		self.assertEqual(availability_status(10, 8), STATUS_NEAR_FULL)
		self.assertEqual(availability_status(10, 9.9), STATUS_NEAR_FULL)

	def test_at_or_over_capacity_is_full(self):
		"""ถึงหรือเกินความจุคือเต็ม"""
		self.assertEqual(availability_status(10, 10), STATUS_FULL)
		self.assertEqual(availability_status(10, 12), STATUS_FULL)

	def test_zero_capacity_is_full(self):
		"""ความจุ 0 แต่ยังไม่ถูกทำเครื่องหมายปิด ถือว่าเต็ม"""
		self.assertEqual(availability_status(0, 0), STATUS_FULL)

	def test_closed_bay_wins_over_numbers(self):
		"""ช่องที่ปิดทำการแสดงปิดทำการเสมอ ไม่ว่าตัวเลขจะเป็นเท่าไร"""
		self.assertEqual(availability_status(8, 0, is_closed=True), STATUS_CLOSED)


class UnitTestBuildCapacityWarnings(UnitTestCase):
	"""ทดสอบข้อความเตือนความจุครบทุกเคส (availability/cap_map ประดิษฐ์)"""

	def make_caps(self, source=CAP_SOURCE_NORMAL, is_closed=False, reason=None, bays=("BAY-01",)):
		return {bay: {"cap": 8, "source": source, "is_closed": is_closed, "reason": reason} for bay in bays}

	def test_no_active_bay_at_all(self):
		"""ไม่มีช่องจอดเปิดใช้งานเลย"""
		warnings = build_capacity_warnings(make_appointment(), [], {}, set())

		self.assertEqual(len(warnings), 1)
		self.assertIn("ยังไม่มีช่องจอดซ่อมที่เปิดใช้งาน", warnings[0])

	def test_weekly_holiday_is_reported(self):
		"""วันหยุดประจำสัปดาห์ต้องเตือน แม้ยังไม่มีการจัดช่องจอด"""
		appointment = make_appointment()
		appointment.appointment_date = "2026-09-06"

		warnings = build_capacity_warnings(
			appointment,
			[make_bay("BAY-01", cap=0, is_closed=True)],
			self.make_caps(source=CAP_SOURCE_WEEKLY_HOLIDAY, is_closed=True),
			set(),
		)

		self.assertEqual(len(warnings), 1)
		self.assertIn("วันหยุดประจำสัปดาห์", warnings[0])

	def test_bay_closed_by_override_mentions_reason(self):
		"""ช่องจอดถูกปิดด้วย override → เตือนพร้อมเหตุผล"""
		appointment = make_appointment(
			bay_rows=[{"service_bay": "BAY-01", "work_type": WORK_TYPE_GENERAL, "allocated_hours": 2}],
		)
		appointment.estimated_duration = 2

		warnings = build_capacity_warnings(
			appointment,
			[make_bay("BAY-01", cap=0, is_closed=True)],
			self.make_caps(source=CAP_SOURCE_OVERRIDE, is_closed=True, reason="อบรมประจำปี"),
			set(),
		)

		self.assertTrue(any("ถูกปิดทำการ" in warning and "อบรมประจำปี" in warning for warning in warnings))

	def test_overtime_warning_per_bay(self):
		"""ชั่วโมงที่จองแล้วบวกงานใหม่เกินความจุ → เตือน OT ของช่องนั้น"""
		appointment = make_appointment(
			bay_rows=[{"service_bay": "BAY-01", "work_type": WORK_TYPE_GENERAL, "allocated_hours": 3}],
		)
		appointment.estimated_duration = 3

		warnings = build_capacity_warnings(
			appointment,
			[make_bay("BAY-01", cap=8, booked=6)],
			self.make_caps(),
			set(),
		)

		self.assertEqual(len(warnings), 1)
		self.assertIn("9.0/8.0 ชม.", warnings[0])
		self.assertIn("OT", warnings[0])

	def test_single_job_longer_than_daily_capacity(self):
		"""งานเดียวยาวกว่าความจุต่อวันของช่อง → เตือนว่างานอาจทำข้ามวัน"""
		appointment = make_appointment(
			bay_rows=[{"service_bay": "BAY-01", "work_type": WORK_TYPE_GENERAL, "allocated_hours": 12}],
		)
		appointment.estimated_duration = 12

		warnings = build_capacity_warnings(
			appointment,
			[make_bay("BAY-01", cap=8)],
			self.make_caps(),
			set(),
		)

		self.assertTrue(any("งานอาจทำข้ามวัน" in warning for warning in warnings))

	def test_pit_work_on_bay_without_pit(self):
		"""แถวงานหลุมถูกจัด (หรือแก้มือ) ลงช่องที่ไม่มีหลุม"""
		appointment = make_appointment(
			service_rows=[{"service_type": "เปลี่ยนน้ำมันเครื่อง", "estimated_time": 2}],
			bay_rows=[{"service_bay": "BAY-01", "work_type": WORK_TYPE_PIT, "allocated_hours": 2}],
		)
		appointment.estimated_duration = 2

		warnings = build_capacity_warnings(
			appointment,
			[make_bay("BAY-01", has_pit=0)],
			self.make_caps(),
			{"เปลี่ยนน้ำมันเครื่อง"},
		)

		self.assertTrue(any("ไม่มีหลุมซ่อม" in warning for warning in warnings))

	def test_stale_allocation_is_reported(self):
		"""ผลรวมชั่วโมงในตารางไม่ตรงกับระยะเวลางาน → แนะให้กดจัด Bay ใหม่"""
		appointment = make_appointment(
			bay_rows=[{"service_bay": "BAY-01", "work_type": WORK_TYPE_GENERAL, "allocated_hours": 2}],
		)
		appointment.estimated_duration = 5

		warnings = build_capacity_warnings(
			appointment,
			[make_bay("BAY-01")],
			self.make_caps(),
			set(),
		)

		self.assertTrue(any("จัด Bay ใหม่" in warning for warning in warnings))

	def test_allocation_on_unknown_bay(self):
		"""ช่องจอดในตารางไม่อยู่ในรายการช่องที่เปิดใช้งานของวันนั้น"""
		appointment = make_appointment(
			bay_rows=[{"service_bay": "BAY-99", "work_type": WORK_TYPE_GENERAL, "allocated_hours": 2}],
		)
		appointment.estimated_duration = 2

		warnings = build_capacity_warnings(
			appointment,
			[make_bay("BAY-01")],
			self.make_caps(),
			set(),
		)

		self.assertTrue(any("ไม่อยู่ในรายการช่องจอดที่เปิดใช้งาน" in warning for warning in warnings))

	def test_clean_allocation_has_no_warnings(self):
		"""จัดช่องจอดพอดี ความจุเหลือ ไม่ต้องเตือนอะไรเลย"""
		appointment = make_appointment(
			bay_rows=[{"service_bay": "BAY-01", "work_type": WORK_TYPE_GENERAL, "allocated_hours": 2}],
		)
		appointment.estimated_duration = 2

		warnings = build_capacity_warnings(
			appointment,
			[make_bay("BAY-01", booked=1)],
			self.make_caps(),
			set(),
		)

		self.assertEqual(warnings, [])

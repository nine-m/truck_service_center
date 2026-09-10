# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.truck_service_center.doctype.service_appointment.service_appointment import (
	CAP_SOURCE_HALF_DAY,
	CAP_SOURCE_NORMAL,
	CAP_SOURCE_OVERRIDE,
	CAP_SOURCE_WEEKLY_HOLIDAY,
	DAY_MODE_CLOSED,
	DAY_MODE_FULL,
	DAY_MODE_HALF,
	NO_ACTIVE_BAY_NOTE,
	STATUS_CLOSED,
	STATUS_FREE,
	STATUS_FULL,
	STATUS_NEAR_FULL,
	WORK_TYPE_GENERAL,
	WORK_TYPE_PIT,
	availability_status,
	build_capacity_warnings,
	build_day_notes,
	build_day_rows,
	compute_allocation,
	fold_booked_hours,
	resolve_bay_caps,
	split_pit_hours,
	summarize_day,
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


def make_bay(bay, cap=8.0, booked=0.0, has_pit=0, is_closed=False, cap_source=CAP_SOURCE_NORMAL, reason=None):
	"""แถว availability ประดิษฐ์ — รูปเดียวกับที่ build_day_rows คืนให้"""
	return {
		"bay": bay,
		"bay_name": bay,
		"has_pit": has_pit,
		"cap": cap,
		"cap_source": cap_source,
		"is_closed": is_closed,
		"reason": reason,
		"booked": booked,
		"free": cap - booked,
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


class UnitTestBuildDayRows(UnitTestCase):
	"""ตรึงรูปแถวรายช่องจอดหลังแยกออกมาเป็น pure function — ห้ามเปลี่ยนพฤติกรรมเดิม"""

	def make_bays(self):
		return [
			{"name": "BAY-01", "bay_name": "ช่อง 1", "has_pit": 1, "daily_capacity_hours": 8},
			{"name": "BAY-02", "bay_name": "ช่อง 2", "has_pit": 0, "daily_capacity_hours": 8},
		]

	def test_row_shape_and_values(self):
		"""แถวต้องมีครบทุกคีย์ที่ฝั่ง client ใช้ และคำนวณ free/status ให้ถูก"""
		bays = self.make_bays()
		caps = resolve_bay_caps(bays, DAY_MODE_FULL, [])
		# 6.4/8 = 80% พอดี — ตรึงขอบเขต NEAR_FULL_RATIO ที่ระดับแถวด้วย
		rows = build_day_rows(bays, caps, {"BAY-01": 6.4})

		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["bay"], "BAY-01")
		self.assertEqual(rows[0]["bay_name"], "ช่อง 1")
		self.assertEqual(rows[0]["has_pit"], 1)
		self.assertEqual(rows[0]["cap"], 8.0)
		self.assertEqual(rows[0]["booked"], 6.4)
		self.assertEqual(rows[0]["free"], 1.6)
		self.assertEqual(rows[0]["cap_source"], CAP_SOURCE_NORMAL)
		self.assertFalse(rows[0]["is_closed"])
		self.assertIsNone(rows[0]["reason"])
		self.assertEqual(rows[0]["status"], STATUS_NEAR_FULL)

		self.assertEqual(rows[1]["booked"], 0.0)
		self.assertEqual(rows[1]["status"], STATUS_FREE)

	def test_free_goes_negative_when_overbooked(self):
		"""จองเกินแล้ว free ต้องติดลบ ไม่ใช่ถูก clamp เป็นศูนย์ — ระดับแถวยังบอก OT ได้"""
		bays = self.make_bays()
		caps = resolve_bay_caps(bays, DAY_MODE_FULL, [])
		rows = build_day_rows(bays, caps, {"BAY-01": 11.0})

		self.assertEqual(rows[0]["free"], -3.0)
		self.assertEqual(rows[0]["status"], STATUS_FULL)

	def test_override_reason_flows_into_row(self):
		"""เหตุผลของ override ต้องไหลลงแถว เพื่อให้ tooltip ปฏิทินบอกสาเหตุที่ปิดได้"""
		bays = self.make_bays()
		overrides = [{"service_bay": "BAY-01", "capacity_hours": 0, "reason": "ซ่อมลิฟต์"}]
		caps = resolve_bay_caps(bays, DAY_MODE_FULL, overrides)
		rows = build_day_rows(bays, caps, {})

		self.assertTrue(rows[0]["is_closed"])
		self.assertEqual(rows[0]["reason"], "ซ่อมลิฟต์")
		self.assertEqual(rows[0]["cap_source"], CAP_SOURCE_OVERRIDE)
		self.assertEqual(rows[0]["status"], STATUS_CLOSED)
		# ช่องที่ไม่ได้ถูก override ต้องไม่โดนหางเลข
		self.assertFalse(rows[1]["is_closed"])

	def test_no_bays_gives_no_rows(self):
		"""ไม่มีช่องจอดก็ไม่มีแถว — ไม่ throw"""
		self.assertEqual(build_day_rows([], {}, {}), [])


class UnitTestBuildDayNotes(UnitTestCase):
	"""ข้อความระดับวันที่เอาไปโชว์ใต้ meter และใน tooltip ของปฏิทิน"""

	def test_weekly_holiday(self):
		self.assertIn("วันหยุดประจำสัปดาห์", build_day_notes(DAY_MODE_CLOSED, []))

	def test_half_day(self):
		self.assertIn("ครึ่งวัน", build_day_notes(DAY_MODE_HALF, []))

	def test_full_day_without_override_has_no_note(self):
		self.assertEqual(build_day_notes(DAY_MODE_FULL, []), "")

	def test_global_close_override_mentions_reason(self):
		"""override ที่เว้นช่องจอดว่าง = มีผลทุกช่อง จึงต้องบอกในระดับวัน"""
		note = build_day_notes(DAY_MODE_FULL, [{"service_bay": None, "capacity_hours": 0, "reason": "ตรุษจีน"}])
		self.assertIn("ปิดทำการทุกช่องจอด", note)
		self.assertIn("ตรุษจีน", note)

	def test_global_reduced_override_shows_hours(self):
		note = build_day_notes(DAY_MODE_FULL, [{"service_bay": None, "capacity_hours": 4, "reason": None}])
		self.assertIn("4.0 ชม.", note)

	def test_bay_specific_override_is_not_a_day_note(self):
		"""override รายช่องไม่ใช่เรื่องระดับวัน — ไปโชว์ที่แถวของช่องนั้นแทน"""
		self.assertEqual(
			build_day_notes(DAY_MODE_FULL, [{"service_bay": "BAY-01", "capacity_hours": 0, "reason": "x"}]),
			"",
		)

	def test_half_day_and_override_are_joined(self):
		note = build_day_notes(DAY_MODE_HALF, [{"service_bay": None, "capacity_hours": 0, "reason": None}])
		self.assertIn(" • ", note)


class UnitTestSummarizeDay(UnitTestCase):
	"""ยอดรวมระดับวัน — ตัวเลขชุดเดียวที่ปฏิทินกับฟอร์มใช้ร่วมกัน"""

	def test_no_bays_is_closed_not_full(self):
		"""ไม่มีช่องจอดเลยคือยังตั้งค่าไม่เสร็จ ไม่ใช่เต็ม — availability_status(0, 0) จะตอบว่าเต็ม"""
		summary = summarize_day([])

		self.assertFalse(summary["has_bays"])
		self.assertEqual(summary["status"], STATUS_CLOSED)
		self.assertEqual(summary["cap"], 0)
		self.assertEqual(summary["booked"], 0)
		self.assertEqual(summary["free"], 0)
		self.assertEqual(summary["over"], 0)
		self.assertEqual(summary["day_note"], NO_ACTIVE_BAY_NOTE)

	def test_plain_sum_when_nothing_is_overbooked(self):
		summary = summarize_day([make_bay("BAY-01", booked=3), make_bay("BAY-02", booked=5)])

		self.assertEqual(summary["cap"], 16)
		self.assertEqual(summary["booked"], 8)
		self.assertEqual(summary["free"], 8)
		self.assertEqual(summary["over"], 0)
		self.assertEqual(summary["status"], STATUS_FREE)

	def test_free_is_clamped_per_bay(self):
		"""BAY-01 10/8 + BAY-02 2/8 = OT 2 ชม. และยังรับได้ 6 ชม. ไม่ใช่ 12/16 ที่ยังว่าง 4 ชม."""
		summary = summarize_day([make_bay("BAY-01", booked=10), make_bay("BAY-02", booked=2)])

		self.assertEqual(summary["booked"], 12)
		self.assertEqual(summary["free"], 6)
		self.assertEqual(summary["over"], 2)
		self.assertEqual(summary["status"], STATUS_FREE)

	def test_status_follows_remaining_hours_not_raw_booked(self):
		"""booked 19 > cap 16 แต่ยังจองได้อีก 1 ชม. → ใกล้เต็ม ไม่ใช่เต็ม"""
		summary = summarize_day([make_bay("BAY-01", booked=12), make_bay("BAY-02", booked=7)])

		self.assertEqual(summary["booked"], 19)
		self.assertEqual(summary["free"], 1)
		self.assertEqual(summary["over"], 4)
		self.assertEqual(summary["status"], STATUS_NEAR_FULL)

	def test_full_when_no_bay_has_room_left(self):
		summary = summarize_day([make_bay("BAY-01", booked=8), make_bay("BAY-02", booked=9)])

		self.assertEqual(summary["free"], 0)
		self.assertEqual(summary["over"], 1)
		self.assertEqual(summary["status"], STATUS_FULL)

	def test_exactly_eighty_percent_is_near_full(self):
		"""ขอบเขต NEAR_FULL_RATIO — 80% พอดีต้องนับเป็นใกล้เต็มแล้ว"""
		summary = summarize_day([make_bay("BAY-01", booked=6.4), make_bay("BAY-02", booked=6.4)])

		self.assertEqual(summary["free"], 3.2)
		self.assertEqual(summary["status"], STATUS_NEAR_FULL)

	def test_all_bays_closed_still_counts_overtime(self):
		"""วันปิดที่มีคนจองไว้ ต้องบอกทั้ง "ปิดทำการ" และ OT ที่เกิดไปแล้ว"""
		rows = [
			make_bay("BAY-01", cap=0, booked=4, is_closed=True),
			make_bay("BAY-02", cap=0, booked=0, is_closed=True),
		]
		summary = summarize_day(rows)

		self.assertTrue(summary["is_closed"])
		self.assertEqual(summary["status"], STATUS_CLOSED)
		self.assertEqual(summary["over"], 4)
		self.assertEqual(summary["free"], 0)

	def test_one_closed_bay_does_not_close_the_day(self):
		rows = [make_bay("BAY-01", cap=0, is_closed=True), make_bay("BAY-02", booked=1)]
		summary = summarize_day(rows)

		self.assertFalse(summary["is_closed"])
		self.assertEqual(summary["cap"], 8)
		self.assertEqual(summary["status"], STATUS_FREE)

	def test_day_note_is_passed_through(self):
		"""มีช่องจอดแล้วต้องใช้ note ที่ส่งมา ไม่ใช่ทับด้วยข้อความว่าไม่มีช่องจอด"""
		summary = summarize_day([make_bay("BAY-01")], "วันนี้ทำครึ่งวัน")
		self.assertEqual(summary["day_note"], "วันนี้ทำครึ่งวัน")


class UnitTestFoldBookedHours(UnitTestCase):
	"""รวมชั่วโมงที่จองแล้วแบบ pure — ครอบแทนการ insert Service Appointment จริง"""

	def test_groups_by_date_and_bay(self):
		appointments = [
			{"name": "APT-1", "appointment_date": "2026-09-10"},
			{"name": "APT-2", "appointment_date": "2026-09-10"},
			{"name": "APT-3", "appointment_date": "2026-09-11"},
		]
		bay_rows = [
			{"parent": "APT-1", "service_bay": "BAY-01", "allocated_hours": 3},
			{"parent": "APT-2", "service_bay": "BAY-01", "allocated_hours": 2},
			{"parent": "APT-2", "service_bay": "BAY-02", "allocated_hours": 1},
			{"parent": "APT-3", "service_bay": "BAY-01", "allocated_hours": 4},
		]

		booked = fold_booked_hours(appointments, bay_rows)

		self.assertEqual(booked["2026-09-10"], {"BAY-01": 5.0, "BAY-02": 1.0})
		self.assertEqual(booked["2026-09-11"], {"BAY-01": 4.0})

	def test_keys_are_iso_strings(self):
		"""key ต้องเป็นสตริงเสมอ แม้ input จะเป็น date object — ฝั่ง JS ใช้ค่านี้ตรงๆ"""
		import datetime

		booked = fold_booked_hours(
			[{"name": "APT-1", "appointment_date": datetime.date(2026, 9, 10)}],
			[{"parent": "APT-1", "service_bay": "BAY-01", "allocated_hours": 2}],
		)

		self.assertEqual(list(booked), ["2026-09-10"])

	def test_rows_without_bay_are_skipped(self):
		"""แถวที่ยังไม่ได้เลือกช่องจอด ไม่กินความจุของใคร"""
		booked = fold_booked_hours(
			[{"name": "APT-1", "appointment_date": "2026-09-10"}],
			[
				{"parent": "APT-1", "service_bay": None, "allocated_hours": 5},
				{"parent": "APT-1", "service_bay": "BAY-01", "allocated_hours": 2},
			],
		)

		self.assertEqual(booked, {"2026-09-10": {"BAY-01": 2.0}})

	def test_appointment_without_bay_rows_has_no_entry(self):
		"""ใบที่ยังไม่ถูกจัดช่องจอด ไม่ควรสร้าง key วันเปล่าๆ ให้ปฏิทินเข้าใจผิด"""
		self.assertEqual(fold_booked_hours([{"name": "APT-1", "appointment_date": "2026-09-10"}], []), {})

	def test_orphan_bay_rows_are_ignored(self):
		"""แถวที่ parent ไม่อยู่ในชุดนัดหมายที่กรองมา (เช่นถูก exclude) ต้องไม่ถูกนับ"""
		booked = fold_booked_hours(
			[{"name": "APT-1", "appointment_date": "2026-09-10"}],
			[{"parent": "APT-OTHER", "service_bay": "BAY-01", "allocated_hours": 9}],
		)

		self.assertEqual(booked, {})

	def test_empty_input(self):
		self.assertEqual(fold_booked_hours([], []), {})

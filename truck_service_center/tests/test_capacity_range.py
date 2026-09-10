# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""ความจุรายวันแบบช่วงวัน สำหรับแปะตัวเลขลงทุกช่องของปฏิทินนัดหมาย

เคสที่ทำให้ต้องมีเทสต์ชุดนี้: ปฏิทินกับฟอร์มนัดหมายอ่านความจุจากคนละ endpoint
(get_capacity_range กับ get_bay_availability) ถ้าสองตัวนี้ให้ตัวเลขไม่ตรงกัน ผู้ใช้จะเห็น
"14/16 ชม." บนปฏิทินแล้วกดเข้าไปเจอเลขอื่นในฟอร์ม ซึ่งพังความน่าเชื่อถือของทั้งหน้า
จึงต้องมีเทสต์ที่ยืนยันว่า summary ของสองทางเท่ากันเป๊ะ

ไม่ insert Service Appointment ที่นี่ — doctype บังคับ customer/vehicle และ validate เต็มใบ
ตรรกะการรวมชั่วโมงที่จองแล้วครอบไว้ใน UnitTestFoldBookedHours แทน
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from truck_service_center.truck_service_center.doctype.service_appointment.service_appointment import (
	MAX_CAPACITY_RANGE_DAYS,
	STATUS_CLOSED,
	get_bay_availability,
	get_capacity_range,
)

# ตั้งชื่อให้ไม่ชนช่องจอดจริงของ site — IntegrationTestCase rollback ให้อยู่แล้ว
# แต่ชื่อที่ชนกันจะทำให้ insert ล้มตั้งแต่แรก (Service Bay autoname = field:bay_name)
TEST_BAY_A = "ZZ-TEST-BAY-01"
TEST_BAY_B = "ZZ-TEST-BAY-02"
OVERRIDE_REASON = "ทดสอบปิดทำการ"


class TestCapacityRange(IntegrationTestCase):
	"""ช่วงวันต้องครบทุกวัน ตัวเลขต้องตรงกับฉบับรายวัน และช่วงยาวผิดปกติต้องถูกปฏิเสธ"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.today = getdate(today())
		# วันที่ปิดด้วย override — เว้น service_bay ว่างเพื่อให้มีผลทุกช่องจอด
		cls.closed_date = getdate(add_days(cls.today, 2))

		for bay_name, has_pit in ((TEST_BAY_A, 1), (TEST_BAY_B, 0)):
			if not frappe.db.exists("Service Bay", bay_name):
				frappe.get_doc(
					{
						"doctype": "Service Bay",
						"bay_name": bay_name,
						"has_pit": has_pit,
						"daily_capacity_hours": 8,
						"is_active": 1,
					}
				).insert()

		frappe.get_doc(
			{
				"doctype": "Bay Capacity Override",
				"override_date": cls.closed_date,
				"capacity_hours": 0,
				"reason": OVERRIDE_REASON,
			}
		).insert()

	def test_every_day_in_range_is_present(self):
		"""ปฏิทินต้องได้ข้อมูลครบทุกช่อง วันที่หายไปหนึ่งวันคือช่องว่างบนหน้าจอ"""
		end = getdate(add_days(self.today, 6))
		result = get_capacity_range(self.today, end)

		self.assertEqual(result["start"], str(self.today))
		self.assertEqual(result["end"], str(end))
		self.assertEqual(len(result["days"]), 7)

		for offset in range(7):
			key = str(getdate(add_days(self.today, offset)))
			self.assertIn(key, result["days"])
			self.assertIn("summary", result["days"][key])
			self.assertIn("bays", result["days"][key])

	def test_bays_cover_every_active_bay(self):
		"""จำนวนแถวต่อวันต้องเท่ากับช่องจอดที่เปิดใช้งานทั้งหมด"""
		active = frappe.db.count("Service Bay", {"is_active": 1})
		days = get_capacity_range(self.today, self.today)["days"]

		self.assertEqual(len(days[str(self.today)]["bays"]), active)

	def test_override_closes_the_day_and_explains_why(self):
		"""override ที่เว้นช่องจอดว่างต้องปิดทั้งวัน และเหตุผลต้องไปโผล่ใน tooltip ได้"""
		result = get_capacity_range(self.closed_date, self.closed_date)
		summary = result["days"][str(self.closed_date)]["summary"]

		self.assertTrue(summary["is_closed"])
		self.assertEqual(summary["status"], STATUS_CLOSED)
		self.assertEqual(summary["cap"], 0)
		self.assertIn(OVERRIDE_REASON, summary["day_note"])

		# ทุกแถวต้องปิดตามไปด้วย ไม่ใช่ปิดแค่ระดับสรุป
		for row in result["days"][str(self.closed_date)]["bays"]:
			self.assertTrue(row["is_closed"])

	def test_matches_single_day_endpoint(self):
		"""ตัวเลขบนปฏิทินกับบนฟอร์มต้องมาจากที่เดียวกัน — นี่คือเทสต์หลักของไฟล์นี้"""
		for date in (self.today, self.closed_date, getdate(add_days(self.today, 5))):
			with self.subTest(date=str(date)):
				from_range = get_capacity_range(date, date)["days"][str(date)]
				from_day = get_bay_availability(date)

				self.assertEqual(from_range["summary"], from_day["summary"])
				self.assertEqual(from_range["bays"], from_day["bays"])

	def test_long_range_is_rejected(self):
		"""ช่วงยาวผิดปกติต้องถูกปฏิเสธ ไม่ใช่ปล่อยให้กวาดตารางทั้งตาราง"""
		with self.assertRaises(frappe.ValidationError):
			get_capacity_range(self.today, add_days(self.today, 200))

	def test_range_at_the_limit_is_allowed(self):
		"""ขอบเขตพอดีต้องผ่าน — กันการเผลอทำ off-by-one จนปฏิทินเดือนใช้ไม่ได้"""
		end = add_days(self.today, MAX_CAPACITY_RANGE_DAYS)
		result = get_capacity_range(self.today, end)

		self.assertEqual(len(result["days"]), MAX_CAPACITY_RANGE_DAYS + 1)

	def test_reversed_range_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			get_capacity_range(self.today, add_days(self.today, -1))

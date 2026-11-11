# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""กราฟการใช้ช่องจอดวันนี้บน dashboard — pure function ล้วน ไม่ insert เอกสาร

เคสที่ต้องกันไว้: นัดที่เปิดใบงานแล้วต้องไม่ถูกนับซ้ำทั้งสองชั้น และงานที่จบไปก่อนวันนี้
ต้องไม่กินความจุของวันนี้
"""

from frappe.tests import UnitTestCase

from truck_service_center.truck_service_center.dashboard_chart_source.tsc_bay_usage_today.tsc_bay_usage_today import (
	build_chart,
	hours_from_appointments,
	hours_from_orders,
)

TODAY = "2026-11-10"


class TestBayUsageChart(UnitTestCase):
	def test_order_rows_fall_back_to_main_bay_and_skip_past_work(self):
		rows = [
			{"main_bay": "B1", "service_bay": None, "estimated_time": 2, "end_time": None},
			{"main_bay": "B1", "service_bay": "B2", "estimated_time": 3, "end_time": None},
			# จบวันนี้ = ใช้ช่องไปแล้ววันนี้ ต้องนับ
			{"main_bay": "B1", "service_bay": None, "estimated_time": 1.5, "end_time": f"{TODAY} 10:00:00"},
			# จบเมื่อวาน = ไม่เกี่ยวกับความจุวันนี้
			{"main_bay": "B1", "service_bay": None, "estimated_time": 4, "end_time": "2026-11-09 16:00:00"},
			# ไม่มีช่องจอดเลย ไม่มีแท่งให้ลง
			{"main_bay": None, "service_bay": None, "estimated_time": 5, "end_time": None},
		]
		self.assertEqual(hours_from_orders(rows, TODAY), {"B1": 3.5, "B2": 3})

	def test_appointments_with_service_order_are_not_double_counted(self):
		appointments = [
			{"name": "APT-1", "service_order": None},
			{"name": "APT-2", "service_order": "SO-1"},
		]
		bay_rows = [
			{"parent": "APT-1", "service_bay": "B1", "allocated_hours": 2},
			{"parent": "APT-1", "service_bay": "B2", "allocated_hours": 1},
			{"parent": "APT-2", "service_bay": "B1", "allocated_hours": 6},
			{"parent": "APT-1", "service_bay": None, "allocated_hours": 9},
		]
		self.assertEqual(hours_from_appointments(appointments, bay_rows), {"B1": 2, "B2": 1})

	def test_chart_stacks_order_scheduled_free(self):
		cap_rows = [
			{"bay": "B1", "bay_name": "Bay 1", "cap": 8, "is_closed": False},
			{"bay": "B2", "bay_name": "Bay 2", "cap": 8, "is_closed": False},
			{"bay": "B3", "bay_name": "Bay 3", "cap": 0, "is_closed": True},
		]
		chart = build_chart(cap_rows, {"B1": 3, "B2": 7, "B3": 2}, {"B1": 2, "B2": 4})

		self.assertEqual(chart["labels"], ["Bay 1", "Bay 2", "Bay 3 (ปิด)"])
		orders, scheduled, free = (dataset["values"] for dataset in chart["datasets"])
		self.assertEqual(orders, [3, 7, 2])
		self.assertEqual(scheduled, [2, 4, 0])
		# จองเกินความจุ = ว่าง 0 ไม่ติดลบ แท่งจะสูงกว่าความจุเอง
		self.assertEqual(free, [3, 0, 0])

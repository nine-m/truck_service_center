# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""ป้าย "กลุ่ม PM เต็ม" บนปฏิทินนัดหมาย — pure function ล้วน ไม่ insert เอกสาร

เคสที่ต้องกันไว้: ช่องที่ปิดทำการต้องไม่ทำให้กลุ่มดูเหมือน "เต็มทุกช่อง" และช่องที่ไม่ได้ผูกกลุ่ม
ต้องไม่โผล่เป็นกลุ่มว่างชื่อ None บนปฏิทิน
"""

from frappe.tests import UnitTestCase

from truck_service_center.truck_service_center.doctype.service_appointment.service_appointment import (
	STATUS_CLOSED,
	STATUS_FREE,
	STATUS_FULL,
	STATUS_NEAR_FULL,
	build_day_rows,
	summarize_pm_groups,
)


def row(bay, group, status, is_closed=False):
	return {"bay": bay, "bay_name": bay, "pm_group": group, "status": status, "is_closed": is_closed}


class TestPMGroups(UnitTestCase):
	def test_all_bays_full_vs_some_bays_full(self):
		rows = [
			row("ES01", "PM1", STATUS_FULL),
			row("ES02", "PM1", STATUS_FULL),
			row("ES03", "PM2", STATUS_FULL),
			row("ES04", "PM2", STATUS_NEAR_FULL),
			row("ES05", "PM2", STATUS_FREE),
		]
		self.assertEqual(
			summarize_pm_groups(rows),
			[
				{"pm_group": "PM1", "open": 2, "full": ["ES01", "ES02"], "all_full": True},
				{"pm_group": "PM2", "open": 3, "full": ["ES03"], "all_full": False},
			],
		)

	def test_groups_without_full_bays_are_left_out(self):
		rows = [row("ES01", "PM1", STATUS_NEAR_FULL), row("ES02", "PM1", STATUS_FREE)]
		self.assertEqual(summarize_pm_groups(rows), [])

	def test_closed_bays_do_not_count_as_open_or_full(self):
		# ช่องที่ปิดไม่นับเป็นช่องที่รับได้ — ช่องที่เหลือเต็ม = กลุ่มนี้รับเพิ่มไม่ได้จริง
		rows = [row("TY1", "PM3", STATUS_FULL), row("TY2", "PM3", STATUS_CLOSED, is_closed=True)]
		self.assertEqual(
			summarize_pm_groups(rows),
			[{"pm_group": "PM3", "open": 1, "full": ["TY1"], "all_full": True}],
		)

	def test_bays_without_group_are_ignored(self):
		rows = [row("EXT-TIRE", None, STATUS_FULL), row("ES01", "PM1", STATUS_FULL)]
		self.assertEqual([g["pm_group"] for g in summarize_pm_groups(rows)], ["PM1"])

	def test_build_day_rows_carries_pm_group(self):
		bays = [{"name": "ES01", "bay_name": "ES01", "bay_type": "GENERAL", "pm_group": "PM1"}]
		caps = {"ES01": {"cap": 8, "source": "bay", "is_closed": False}}
		rows = build_day_rows(bays, caps, {"ES01": 8})
		self.assertEqual(rows[0]["pm_group"], "PM1")
		self.assertEqual(summarize_pm_groups(rows)[0]["full"], ["ES01"])

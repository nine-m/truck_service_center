# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""หน้าใบเบิกอะไหล่ของพอร์ทัลช่าง — งานที่ผู้ใช้เลือกผูกอะไหล่ที่ขอเพิ่มได้

ตัวเลือกบนหน้าจอต้องตรงกับด่านจริง (_get_group_job) ไม่งั้นช่างจะเห็นงานที่กดส่งแล้วโดน
PermissionError หรือกลับกัน คือไม่เห็นงานที่ตัวเองมีสิทธิ์ขอ
"""

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.www.service_order_parts import build_request_targets

GROUP_NAMES = {"ENG": "เครื่องยนต์", "BRK": "เบรก"}


def _row(name, label, group="", mine=False, package=""):
	return frappe._dict(name=name, label=label, group=group, mine=mine, package=package)


class UnitTestBuildRequestTargets(UnitTestCase):
	def setUp(self):
		self.rows = [
			_row("r1", "เปลี่ยนน้ำมันเครื่อง", "ENG", mine=True),
			_row("r2", "เปลี่ยนผ้าเบรก", "BRK"),
			_row("r3", "ล้างรถ"),
		]

	def test_technician_sees_own_group_rows_ungrouped_rows_and_no_job(self):
		targets = build_request_targets(self.rows, GROUP_NAMES, job_access=True)
		self.assertEqual([t.row for t in targets], ["r1", "r3", ""])
		self.assertEqual(targets[0].group_label, "เครื่องยนต์")

	def test_supervisor_outside_job_sees_only_supervised_group(self):
		# หัวหน้างานกลุ่มที่ไม่ได้อยู่ในใบ จึงไม่ได้อยู่บนแถวไหนเลย (mine=False ทุกแถว)
		rows = [frappe._dict(row, mine=False) for row in self.rows]
		targets = build_request_targets(rows, GROUP_NAMES, supervised_groups={"BRK"}, job_access=False)
		self.assertEqual([t.row for t in targets], ["r2"])

	def test_manager_sees_everything(self):
		targets = build_request_targets(self.rows, GROUP_NAMES, is_manager=True, job_access=True)
		self.assertEqual([t.row for t in targets], ["r1", "r2", "r3", ""])

	def test_duplicate_service_and_package_collapse_to_one_choice(self):
		rows = [
			_row("a", "PM", "ENG", mine=True, package="PKG"),
			_row("b", "PM", "ENG", mine=True, package="PKG"),
			_row("c", "PM", "ENG", mine=True),
		]
		targets = build_request_targets(rows, GROUP_NAMES, job_access=True)
		self.assertEqual([t.row for t in targets], ["a", "c", ""])

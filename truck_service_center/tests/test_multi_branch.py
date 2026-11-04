# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""หลายสาขาใต้ Company เดียว — ขอบเขตข้อมูล ค่าตั้งของสาขา และสิทธิ์ตาม User Permission

สร้างสาขา/ช่องจอด/ผู้ใช้ทดสอบใน transaction แล้ว rollback ใน tearDown ทุกเทสต์
(ไม่มีอะไรในชุดนี้ commit — frappe.db.rollback ล้างทิ้งหมด)
"""

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.branches import (
	branch_filters,
	branch_prefix,
	branch_sql_condition,
	filter_users_by_branch,
	get_allowed_branches,
	get_branch_settings,
	get_default_branch,
	validate_bays_in_branch,
)
from truck_service_center.truck_service_center.doctype.bay_type.bay_type import get_default_bay_type
from truck_service_center.truck_service_center.doctype.service_appointment.service_appointment import (
	get_bay_availability,
)
from truck_service_center.truck_service_center.doctype.service_order.service_order import (
	can_approve_requisition,
	get_default_parts_warehouse,
)

TEST_DATE = "2031-03-03"  # วันจันทร์ — ไกลพอไม่ชนนัดจริง


def make_branch(code, **fields):
	return frappe.get_doc(
		{"doctype": "Service Branch", "branch_code": code, "branch_name": f"สาขา {code}", **fields}
	).insert()


def make_bay(name, branch, hours=8):
	return frappe.get_doc(
		{
			"doctype": "Service Bay",
			"bay_name": name,
			"branch": branch,
			"bay_type": get_default_bay_type(),
			"daily_capacity_hours": hours,
			"is_active": 1,
		}
	).insert()


def make_user(email, roles=(), branches=()):
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"user_type": "System User",
			"roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)
	for branch in branches:
		frappe.get_doc(
			{"doctype": "User Permission", "user": user.name, "allow": "Service Branch", "for_value": branch}
		).insert(ignore_permissions=True)
	return user.name


class TestMultiBranch(UnitTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.a = make_branch("TSTA", document_prefix="TSTA").name
		self.b = make_branch("TSTB").name

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_cache()

	# ── master สาขา ─────────────────────────────────────────────────────────

	def test_branch_code_must_be_plain(self):
		with self.assertRaises(frappe.ValidationError):
			make_branch("BAD CODE")

	def test_tax_branch_code_is_five_digits(self):
		with self.assertRaises(frappe.ValidationError):
			make_branch("TSTC", tax_branch_code="2")
		self.assertEqual(make_branch("TSTD", tax_branch_code="00002").tax_branch_code, "00002")

	def test_document_prefix_is_unique(self):
		with self.assertRaises(frappe.ValidationError):
			make_branch("TSTE", document_prefix="TSTA")

	# ── ค่าตั้งของสาขา ───────────────────────────────────────────────────────

	def test_branch_settings_override_only_what_is_set(self):
		central = frappe.get_cached_doc("Truck Service Center Settings")
		frappe.db.set_value("Service Branch", self.a, "work_day_monday", "หยุด")

		merged = get_branch_settings(self.a)
		self.assertEqual(merged.work_day_monday, "หยุด")
		self.assertEqual(merged.work_day_tuesday, central.work_day_tuesday)
		self.assertEqual(merged.default_company, central.default_company)
		# ค่ากลางที่ cache ไว้ต้องไม่เปื้อน
		self.assertNotEqual(frappe.get_cached_doc("Truck Service Center Settings").work_day_monday, "หยุด")

	def test_branch_without_overrides_returns_central_settings(self):
		central = frappe.get_cached_doc("Truck Service Center Settings")
		self.assertIs(get_branch_settings(self.b), central)
		self.assertIs(get_branch_settings(None), central)

	def test_parts_warehouse_comes_from_branch(self):
		company = frappe.db.get_single_value("Truck Service Center Settings", "default_company")
		warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
		if not warehouse:
			self.skipTest("ไม่มีคลังของบริษัทหลักบนไซต์นี้")
		frappe.db.set_value("Service Branch", self.a, "default_source_warehouse", warehouse)
		self.assertEqual(get_default_parts_warehouse(self.a), warehouse)

	# ── เลขเอกสาร ────────────────────────────────────────────────────────────

	def test_branch_prefix_in_naming_series(self):
		self.assertEqual(branch_prefix(frappe._dict(branch=self.a)), "TSTA-")
		# สาขาที่ไม่ตั้งรหัสนำหน้า = ชุดเลขเดิม (SO-2026-xxxxx)
		self.assertEqual(branch_prefix(frappe._dict(branch=self.b)), "")
		self.assertEqual(branch_prefix(None), "")

	# ── ความจุช่องจอดแยกสาขา ─────────────────────────────────────────────────

	def test_availability_counts_only_the_branch_bays(self):
		make_bay("TST-BAY-A", self.a)
		make_bay("TST-BAY-B", self.b)

		bays_a = {row["bay"] for row in get_bay_availability(TEST_DATE, branch=self.a)["bays"]}
		self.assertIn("TST-BAY-A", bays_a)
		self.assertNotIn("TST-BAY-B", bays_a)

	def test_branch_work_days_apply_to_availability(self):
		make_bay("TST-BAY-A", self.a)
		frappe.db.set_value("Service Branch", self.a, "work_day_monday", "หยุด")

		availability = get_bay_availability(TEST_DATE, branch=self.a)
		self.assertTrue(availability["day_closed"])

	def test_whole_branch_closure_does_not_close_other_branch(self):
		make_bay("TST-BAY-A", self.a)
		make_bay("TST-BAY-B", self.b)
		frappe.get_doc(
			{
				"doctype": "Bay Capacity Override",
				"override_date": TEST_DATE,
				"branch": self.a,
				"capacity_hours": 0,
				"reason": "test",
			}
		).insert()
		# อีกสาขาปิดวันเดียวกันได้ ไม่ชนกฎห้ามซ้ำ
		frappe.get_doc(
			{
				"doctype": "Bay Capacity Override",
				"override_date": TEST_DATE,
				"branch": self.b,
				"capacity_hours": 4,
				"reason": "test",
			}
		).insert()

		self.assertTrue(get_bay_availability(TEST_DATE, branch=self.a)["day_closed"])
		self.assertFalse(get_bay_availability(TEST_DATE, branch=self.b)["day_closed"])

	def test_override_of_a_bay_takes_the_bay_branch(self):
		make_bay("TST-BAY-B", self.b)
		override = frappe.get_doc(
			{
				"doctype": "Bay Capacity Override",
				"override_date": TEST_DATE,
				"branch": self.a,
				"service_bay": "TST-BAY-B",
				"capacity_hours": 2,
			}
		).insert()
		self.assertEqual(override.branch, self.b)

	def test_bay_of_another_branch_is_rejected(self):
		make_bay("TST-BAY-B", self.b)
		with self.assertRaises(frappe.ValidationError):
			validate_bays_in_branch(self.a, ["TST-BAY-B"])
		validate_bays_in_branch(self.b, ["TST-BAY-B", None])

	# ── สิทธิ์ตามสาขา ────────────────────────────────────────────────────────

	def test_allowed_branches_follow_user_permission(self):
		restricted = make_user("tsc-branch-a@example.com", branches=[self.a])
		free = make_user("tsc-branch-free@example.com")

		self.assertEqual(get_allowed_branches(restricted), [self.a])
		self.assertIsNone(get_allowed_branches(free))
		self.assertIsNone(get_allowed_branches("Administrator"))

		self.assertEqual(branch_filters({}, user=restricted), {"branch": ["in", [self.a]]})
		self.assertEqual(branch_filters({"x": 1}, user=free), {"x": 1})

	def test_default_branch_is_the_users_only_branch(self):
		user = make_user("tsc-branch-b@example.com", branches=[self.b])
		self.assertEqual(get_default_branch(user), self.b)

	def test_report_condition_restricts_to_users_branches(self):
		user = make_user("tsc-branch-a@example.com", branches=[self.a])
		frappe.set_user(user)

		filters = {}
		self.assertIn("so.branch in", branch_sql_condition(filters))
		self.assertEqual(filters["allowed_branches"], (self.a,))

		with self.assertRaises(frappe.PermissionError):
			branch_sql_condition({"branch": self.b})

		# ประวัติซ่อมรถตั้งใจให้เห็นข้ามสาขา
		self.assertEqual(branch_sql_condition({}, restrict=False), "")

	def test_technician_list_excludes_other_branch(self):
		tech_a = make_user("tsc-tech-a@example.com", roles=["Technician"], branches=[self.a])
		tech_any = make_user("tsc-tech-any@example.com", roles=["Technician"])

		self.assertEqual(filter_users_by_branch([tech_a, tech_any], self.b), [tech_any])
		self.assertEqual(filter_users_by_branch([tech_a, tech_any], self.a), [tech_a, tech_any])

	def test_manager_cannot_approve_requisition_of_other_branch(self):
		manager_a = make_user("tsc-manager-a@example.com", roles=["Technician Manager"], branches=[self.a])

		self.assertTrue(can_approve_requisition(frappe._dict(custom_branch=self.a), manager_a))
		self.assertFalse(can_approve_requisition(frappe._dict(custom_branch=self.b), manager_a))
		# ใบเบิกเก่าที่ไม่มีสาขา ตัดสินด้วย role อย่างเดียวเหมือนเดิม
		self.assertTrue(can_approve_requisition(frappe._dict(custom_branch=None), manager_a))

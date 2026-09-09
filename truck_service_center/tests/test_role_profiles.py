# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""ชุด role สำเร็จรูปที่ผู้ดูแลระบบเลือกตอนสร้าง user

เคสที่ทำให้ต้องมีเทสต์ชุดนี้: user ใหม่ที่ไม่ได้เป็น Administrator/System Manager
และไม่ได้ติ๊ก role ของศูนย์บริการเลย จะล็อกอินมาแล้วไม่เห็นหน้าหลักของระบบ
(frappe ตอบ "No App" แล้วส่งไป /me) เพราะ workspace ของแอปโผล่ก็ต่อเมื่อ
โมดูล "Truck Service Center" อยู่ใน allow_modules ซึ่งไล่มาจาก doctype ที่อ่านได้
"""

import frappe
from frappe.tests import IntegrationTestCase

from truck_service_center.install import DEFAULT_ROLE_PROFILES, create_default_role_profiles

# doctype ของ ERPNext ที่ฟอร์มของแอปต้องอ่านให้ได้ ไม่งั้นเลือกลูกค้า/อะไหล่ไม่ได้เลย
ERPNEXT_LINKS = ("Customer", "Item")


class TestDefaultRoleProfiles(IntegrationTestCase):
	"""profile ต้องมีจริงและต้องพอใช้งาน ไม่ใช่แค่มีชื่อ"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_default_role_profiles()

	def test_service_profiles_exist(self):
		"""ธุรการและผู้จัดการศูนย์ต้องมีชุด role ให้เลือก ไม่ใช่มีแต่ฝั่งช่าง"""
		for profile_name in ("Service User", "Service Manager"):
			self.assertTrue(
				frappe.db.exists("Role Profile", profile_name),
				f"ไม่พบ Role Profile {profile_name}",
			)

	def test_profiles_carry_their_own_app_role(self):
		"""ทุก profile ต้องพ่วง role ของแอปที่ชื่อตรงกับ profile มาด้วย"""
		for profile_name in DEFAULT_ROLE_PROFILES:
			doc = frappe.get_doc("Role Profile", profile_name)
			roles = {row.role for row in doc.roles}
			self.assertIn(profile_name, roles, f"{profile_name} ไม่มี role ชื่อเดียวกัน")

	def test_seeder_is_idempotent(self):
		"""เรียกซ้ำต้องไม่เพิ่ม role ซ้ำ — patch กับ after_install เรียกตัวเดียวกัน"""
		before = [row.role for row in frappe.get_doc("Role Profile", "Service User").roles]
		create_default_role_profiles()
		after = [row.role for row in frappe.get_doc("Role Profile", "Service User").roles]
		self.assertEqual(before, after)

	def test_seeder_keeps_hand_added_roles(self):
		"""role ที่ผู้ดูแลระบบเพิ่มเองต้องอยู่ครบหลังรัน seeder ซ้ำ"""
		doc = frappe.get_doc("Role Profile", "Service User")
		doc.append("roles", {"role": "Projects User"})
		doc.save()

		create_default_role_profiles()

		roles = {row.role for row in frappe.get_doc("Role Profile", "Service User").roles}
		self.assertIn("Projects User", roles)


class TestServiceProfilePermissions(IntegrationTestCase):
	"""user ที่สร้างจาก profile ต้องเห็นหน้าหลักและกรอกฟอร์มได้จริง"""

	def setUp(self):
		create_default_role_profiles()

	def _make_user(self, email, profile):
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)

		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
				"role_profiles": [{"role_profile": profile}],
			}
		)
		user.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "User", email, force=1, ignore_permissions=True)
		self.addCleanup(frappe.set_user, "Administrator")
		return email

	def test_service_user_sees_workspace_and_can_fill_forms(self):
		"""ธุรการต้องเห็นหน้าหลัก และอ่าน Customer/Item ได้ ไม่งั้นเปิดใบสั่งงานไม่ได้"""
		user = self._make_user("tsc_profile_advisor@example.com", "Service User")
		frappe.set_user(user)
		frappe.clear_cache(user=user)

		self.assertIn("Truck Service Center", frappe.get_user().load_user().allow_modules)
		for doctype in ERPNEXT_LINKS:
			self.assertTrue(frappe.has_permission(doctype, "read"), f"อ่าน {doctype} ไม่ได้")
		self.assertTrue(frappe.has_permission("Service Order", "create"))

	def test_service_manager_can_raise_the_invoice(self):
		"""ผู้จัดการศูนย์กดออกใบแจ้งหนี้เอง — create_sales_invoice ไม่ได้ ignore_permissions"""
		user = self._make_user("tsc_profile_manager@example.com", "Service Manager")
		frappe.set_user(user)
		frappe.clear_cache(user=user)

		self.assertIn("Truck Service Center", frappe.get_user().load_user().allow_modules)
		self.assertTrue(frappe.has_permission("Sales Invoice", "create"))
		self.assertTrue(frappe.has_permission("Stock Entry", "create"))

# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""เริ่มใช้หลายสาขา — ทุกอย่างที่มีอยู่แล้วถูกจัดเข้า "สาขาหลัก" ระบบจึงทำงานเหมือนเดิมหลัง migrate

- สร้างสาขาหลัก (HQ) ถ้ายังไม่มีสาขาเลย และตั้งเป็นสาขาเริ่มต้นใน Settings
- เติมสาขาให้เอกสาร/ช่องจอด/การปรับความจุ ที่ยังไม่มีสาขา (ระบบเดาไม่ได้ว่าใบเก่าเป็นของสาขาไหน)
- เพิ่มฟิลด์ custom_branch บน Stock Entry / Sales Invoice แล้วเติมจากใบสั่งงานที่ผูกอยู่

สาขาหลักไม่ตั้งรหัสนำหน้าเลขเอกสาร เลขของสาขาหลักจึงรันต่อจากชุดเดิม (SO-2026-xxxxx)
ค่าคลัง/ศูนย์ต้นทุน/วันทำการของสาขาหลักเว้นว่าง = ใช้ค่ากลางใน Settings เหมือนเดิม
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from truck_service_center.branches import BRANCH_DOCTYPES
from truck_service_center.install import CUSTOM_FIELDS

DEFAULT_BRANCH_CODE = "HQ"


def execute():
	create_custom_fields(CUSTOM_FIELDS)

	branch = ensure_default_branch()
	if not branch:
		return

	for doctype in BRANCH_DOCTYPES:
		table = f"tab{doctype}"
		frappe.db.sql(
			f"update `{table}` set branch = %s where branch is null or branch = ''",
			branch,
		)

	for doctype, link in (("Stock Entry", "custom_service_order"), ("Sales Invoice", None)):
		if not frappe.db.has_column(doctype, "custom_branch"):
			continue
		if link:
			frappe.db.sql(
				f"""update `tab{doctype}` d join `tabService Order` so on so.name = d.{link}
				set d.custom_branch = so.branch
				where (d.custom_branch is null or d.custom_branch = '')"""
			)
		else:
			frappe.db.sql(
				"""update `tabSales Invoice` d join `tabService Order` so on so.sales_invoice = d.name
				set d.custom_branch = so.branch
				where (d.custom_branch is null or d.custom_branch = '')"""
			)


def ensure_default_branch():
	"""สาขาเริ่มต้นใน Settings → สาขาแรกที่มีอยู่ → สร้าง HQ ใหม่"""
	default = frappe.db.get_single_value("Truck Service Center Settings", "default_branch")
	if default and frappe.db.exists("Service Branch", default):
		return default

	branch = frappe.db.get_value("Service Branch", {}, "name", order_by="creation asc")
	if not branch:
		doc = frappe.get_doc(
			{
				"doctype": "Service Branch",
				"branch_code": DEFAULT_BRANCH_CODE,
				"branch_name": "สาขาหลัก",
				"is_active": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		branch = doc.name

	frappe.db.set_single_value("Truck Service Center Settings", "default_branch", branch)
	return branch

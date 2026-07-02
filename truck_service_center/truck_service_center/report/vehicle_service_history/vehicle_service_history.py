# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""ประวัติการซ่อมรายคัน — รายการ Service Order ของรถแต่ละคัน พร้อมงานที่ทำและยอดเงิน"""

import frappe


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"fieldname": "service_order",
			"label": "ใบสั่งงาน",
			"fieldtype": "Link",
			"options": "Service Order",
			"width": 150,
		},
		{"fieldname": "service_date", "label": "วันที่", "fieldtype": "Date", "width": 105},
		{
			"fieldname": "vehicle",
			"label": "ทะเบียนรถ",
			"fieldtype": "Link",
			"options": "Vehicle",
			"width": 130,
		},
		{
			"fieldname": "customer",
			"label": "ลูกค้า",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 160,
		},
		{"fieldname": "current_mileage", "label": "เลขไมล์ (กม.)", "fieldtype": "Int", "width": 110},
		{"fieldname": "services", "label": "งานที่ทำ", "fieldtype": "Data", "width": 320},
		{"fieldname": "status", "label": "สถานะ", "fieldtype": "Data", "width": 100},
		{"fieldname": "total_amount", "label": "ยอดรวม", "fieldtype": "Currency", "width": 120},
		{"fieldname": "payment_status", "label": "การชำระเงิน", "fieldtype": "Data", "width": 110},
		{
			"fieldname": "sales_invoice",
			"label": "ใบแจ้งหนี้",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
	]


def get_data(filters):
	conditions = ""

	if filters.get("vehicle"):
		conditions += " and so.vehicle = %(vehicle)s"
	if filters.get("customer"):
		conditions += " and so.customer = %(customer)s"
	if filters.get("from_date"):
		conditions += " and so.service_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " and so.service_date <= %(to_date)s"
	if filters.get("status"):
		conditions += " and so.status = %(status)s"

	return frappe.db.sql(
		f"""
		select
			so.name as service_order,
			so.service_date,
			so.vehicle,
			so.customer,
			so.current_mileage,
			(
				select group_concat(st.service_type separator ', ')
				from `tabService Order Service Type` st
				where st.parent = so.name
			) as services,
			so.status,
			so.total_amount,
			so.payment_status,
			so.sales_invoice
		from `tabService Order` so
		where so.docstatus < 2 {conditions}
		order by so.service_date desc, so.name desc
		""",
		filters,
		as_dict=1,
	)

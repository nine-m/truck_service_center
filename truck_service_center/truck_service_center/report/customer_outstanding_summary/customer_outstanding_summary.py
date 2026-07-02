# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""ยอดค้างชำระรายลูกค้า — สรุปจาก Service Order ที่ submit แล้วและยังมียอดค้าง
(ยอดชำระซิงค์จาก Sales Invoice — ดู sync_payment_from_sales_invoice)"""

import frappe
from frappe.utils import date_diff, nowdate


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"fieldname": "customer",
			"label": "ลูกค้า",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 160,
		},
		{"fieldname": "customer_name", "label": "ชื่อลูกค้า", "fieldtype": "Data", "width": 220},
		{"fieldname": "order_count", "label": "ใบงานค้างชำระ", "fieldtype": "Int", "width": 120},
		{"fieldname": "unbilled_count", "label": "ยังไม่ออกบิล", "fieldtype": "Int", "width": 110},
		{"fieldname": "total_amount", "label": "ยอดรวม", "fieldtype": "Currency", "width": 130},
		{"fieldname": "paid_amount", "label": "ชำระแล้ว", "fieldtype": "Currency", "width": 130},
		{"fieldname": "outstanding_amount", "label": "ค้างชำระ", "fieldtype": "Currency", "width": 130},
		{"fieldname": "oldest_date", "label": "ค้างเก่าสุด", "fieldtype": "Date", "width": 105},
		{"fieldname": "days_overdue", "label": "ค้างนาน (วัน)", "fieldtype": "Int", "width": 105},
	]


def get_data(filters):
	conditions = ""
	if filters.get("customer"):
		conditions += " and so.customer = %(customer)s"
	if filters.get("from_date"):
		conditions += " and so.service_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " and so.service_date <= %(to_date)s"

	rows = frappe.db.sql(
		f"""
		select
			so.customer,
			c.customer_name,
			count(*) as order_count,
			sum(case when ifnull(so.sales_invoice, '') = '' then 1 else 0 end) as unbilled_count,
			sum(so.total_amount) as total_amount,
			sum(so.paid_amount) as paid_amount,
			sum(so.outstanding_amount) as outstanding_amount,
			min(so.service_date) as oldest_date
		from `tabService Order` so
		left join `tabCustomer` c on c.name = so.customer
		where so.docstatus = 1 and so.outstanding_amount > 0 {conditions}
		group by so.customer
		order by outstanding_amount desc
		""",
		filters,
		as_dict=1,
	)

	for row in rows:
		row.days_overdue = date_diff(nowdate(), row.oldest_date) if row.oldest_date else 0

	return rows

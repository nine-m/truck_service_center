# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""รายได้ตามกลุ่มบริการ — ค่าแรงจาก Service Order ที่ submit แล้ว แยกตาม Service Type Group
พร้อมแถว "อะไหล่" รวมยอดขายอะไหล่ (ยอดหลังส่วนลดรายบรรทัด ก่อนส่วนลดท้ายบิล/VAT)"""

import frappe
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	data = get_data(filters)
	chart = get_chart(data)
	return get_columns(), data, None, chart


def get_columns():
	return [
		{
			"fieldname": "service_type_group",
			"label": "กลุ่มบริการ",
			"fieldtype": "Link",
			"options": "Service Type Group",
			"width": 130,
		},
		{"fieldname": "group_name", "label": "ชื่อกลุ่ม", "fieldtype": "Data", "width": 220},
		{"fieldname": "line_count", "label": "จำนวนรายการ", "fieldtype": "Int", "width": 115},
		{"fieldname": "order_count", "label": "จำนวนใบงาน", "fieldtype": "Int", "width": 110},
		{"fieldname": "revenue", "label": "รายได้", "fieldtype": "Currency", "width": 140},
		{"fieldname": "revenue_pct", "label": "% ของรายได้", "fieldtype": "Percent", "width": 110},
	]


def _conditions(filters):
	conditions = ""
	if filters.get("from_date"):
		conditions += " and so.service_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " and so.service_date <= %(to_date)s"
	if filters.get("customer"):
		conditions += " and so.customer = %(customer)s"
	return conditions


def get_data(filters):
	conditions = _conditions(filters)

	# ค่าแรง แยกตามกลุ่มบริการ
	rows = frappe.db.sql(
		f"""
		select
			st.service_type_group,
			g.group_name,
			count(*) as line_count,
			count(distinct st.parent) as order_count,
			sum(st.amount) as revenue
		from `tabService Order Service Type` st
		inner join `tabService Order` so on so.name = st.parent
		left join `tabService Type Group` g on g.name = st.service_type_group
		where so.docstatus = 1 {conditions}
		group by st.service_type_group
		""",
		filters,
		as_dict=1,
	)

	for row in rows:
		if not row.service_type_group:
			row.group_name = "ไม่ระบุกลุ่ม"

	# อะไหล่ รวมเป็นแถวเดียว
	parts = frappe.db.sql(
		f"""
		select
			count(*) as line_count,
			count(distinct si.parent) as order_count,
			sum(si.amount) as revenue
		from `tabService Order Item` si
		inner join `tabService Order` so on so.name = si.parent
		where so.docstatus = 1 {conditions}
		""",
		filters,
		as_dict=1,
	)[0]

	if parts.line_count:
		rows.append(
			frappe._dict(
				service_type_group=None,
				group_name="อะไหล่ (Parts)",
				line_count=parts.line_count,
				order_count=parts.order_count,
				revenue=parts.revenue,
			)
		)

	rows.sort(key=lambda r: flt(r.revenue), reverse=True)

	total = sum(flt(r.revenue) for r in rows)
	for row in rows:
		row.revenue_pct = flt(row.revenue) / total * 100 if total else 0

	return rows


def get_chart(data):
	if not data:
		return None

	return {
		"data": {
			"labels": [row.group_name or row.service_type_group or "-" for row in data],
			"datasets": [{"name": "รายได้", "values": [flt(row.revenue) for row in data]}],
		},
		"type": "bar",
		"colors": ["#449CF0"],
	}

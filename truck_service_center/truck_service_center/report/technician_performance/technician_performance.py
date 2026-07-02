# Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
# For license information, please see license.txt

"""ประสิทธิภาพช่าง — สรุปจาก Service Order ที่ submit แล้ว

ใบงานหนึ่งมีช่างได้สูงสุด 4 คน (technician..technician_4) — ใบงานที่ทำร่วมกัน
จะถูกนับให้ช่างทุกคนเต็มใบ (จำนวนงาน/ชั่วโมง/ยอดเงิน ไม่ได้หารเฉลี่ย)
ประสิทธิภาพ = เวลาประเมิน / เวลาจริง * 100 (เกิน 100% คือทำเสร็จเร็วกว่าประเมิน)
"""

import frappe
from frappe.utils import flt

TECHNICIAN_FIELDS = ("technician", "technician_2", "technician_3", "technician_4")


def execute(filters=None):
	filters = filters or {}
	data = get_data(filters)
	chart = get_chart(data)
	return get_columns(), data, None, chart


def get_columns():
	return [
		{
			"fieldname": "technician",
			"label": "ช่าง",
			"fieldtype": "Link",
			"options": "User",
			"width": 200,
		},
		{"fieldname": "technician_name", "label": "ชื่อ", "fieldtype": "Data", "width": 180},
		{"fieldname": "order_count", "label": "จำนวนใบงาน", "fieldtype": "Int", "width": 110},
		{"fieldname": "estimated_hours", "label": "เวลาประเมินรวม (ชม.)", "fieldtype": "Float", "width": 155},
		{"fieldname": "actual_hours", "label": "เวลาจริงรวม (ชม.)", "fieldtype": "Float", "width": 140},
		{"fieldname": "avg_hours", "label": "เวลาเฉลี่ย/งาน (ชม.)", "fieldtype": "Float", "width": 150},
		{"fieldname": "efficiency", "label": "ประสิทธิภาพ (%)", "fieldtype": "Percent", "width": 125},
		{"fieldname": "revenue", "label": "ยอดงานที่มีส่วนร่วม", "fieldtype": "Currency", "width": 150},
	]


def get_data(filters):
	conditions = ""
	if filters.get("from_date"):
		conditions += " and so.service_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " and so.service_date <= %(to_date)s"

	orders = frappe.db.sql(
		f"""
		select
			so.name, so.technician, so.technician_2, so.technician_3, so.technician_4,
			so.estimated_time, so.actual_time, so.total_amount
		from `tabService Order` so
		where so.docstatus = 1 {conditions}
		""",
		filters,
		as_dict=1,
	)

	stats = {}
	for order in orders:
		technicians = {order.get(f) for f in TECHNICIAN_FIELDS if order.get(f)}
		for tech in technicians:
			if filters.get("technician") and tech != filters.get("technician"):
				continue
			row = stats.setdefault(
				tech,
				frappe._dict(
					technician=tech,
					order_count=0,
					estimated_hours=0,
					actual_hours=0,
					revenue=0,
				),
			)
			row.order_count += 1
			row.estimated_hours += flt(order.estimated_time)
			row.actual_hours += flt(order.actual_time)
			row.revenue += flt(order.total_amount)

	full_names = {}
	if stats:
		full_names = dict(
			frappe.get_all(
				"User",
				filters={"name": ["in", list(stats)]},
				fields=["name", "full_name"],
				as_list=1,
			)
		)

	data = sorted(stats.values(), key=lambda r: r.order_count, reverse=True)
	for row in data:
		row.technician_name = full_names.get(row.technician, "")
		row.avg_hours = flt(row.actual_hours / row.order_count, 2) if row.order_count else 0
		row.efficiency = flt(row.estimated_hours / row.actual_hours * 100, 1) if row.actual_hours else 0

	return data


def get_chart(data):
	if not data:
		return None

	return {
		"data": {
			"labels": [row.technician_name or row.technician for row in data],
			"datasets": [
				{"name": "จำนวนใบงาน", "values": [row.order_count for row in data]},
			],
		},
		"type": "bar",
		"colors": ["#29CD42"],
	}

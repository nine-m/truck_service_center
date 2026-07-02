// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Revenue by Service Group"] = {
	filters: [
		{
			fieldname: "from_date",
			label: "ตั้งแต่วันที่",
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: "ถึงวันที่",
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "customer",
			label: "ลูกค้า",
			fieldtype: "Link",
			options: "Customer",
		},
	],
};

// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Technician Performance"] = {
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
			fieldname: "technician",
			label: "ช่าง",
			fieldtype: "Link",
			options: "User",
		},
	],
};

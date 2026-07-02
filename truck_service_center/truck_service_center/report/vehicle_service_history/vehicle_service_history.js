// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Vehicle Service History"] = {
	filters: [
		{
			fieldname: "vehicle",
			label: "ทะเบียนรถ",
			fieldtype: "Link",
			options: "Vehicle",
		},
		{
			fieldname: "customer",
			label: "ลูกค้า",
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "from_date",
			label: "ตั้งแต่วันที่",
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -12),
		},
		{
			fieldname: "to_date",
			label: "ถึงวันที่",
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "status",
			label: "สถานะ",
			fieldtype: "Select",
			options: "\nDraft\nIn Progress\nCompleted\nCancelled\nOn Hold",
		},
	],
};

// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Customer Outstanding Summary"] = {
	filters: [
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
		},
		{
			fieldname: "to_date",
			label: "ถึงวันที่",
			fieldtype: "Date",
		},
	],
};

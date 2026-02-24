frappe.listview_settings['Service Order'] = {
	add_fields: ["status", "customer", "vehicle", "service_date", "total_amount"],
	has_indicator_for_draft: 1,

	get_indicator: function(doc) {
		// แสดง indicator ตาม status แทน docstatus
		const status_colors = {
			"Draft": "red",
			"In Progress": "orange", 
			"Completed": "green",
			"Cancelled": "gray",
			"On Hold": "yellow"
		};
		
		return [__(doc.status), status_colors[doc.status] || "gray", "status,=," + doc.status];
	}
};

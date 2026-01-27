frappe.listview_settings['Service Order'] = {
	add_fields: ["status", "customer", "vehicle", "service_date", "total_amount"],
	
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
	},
	
	onload: function(listview) {
		// ซ่อนคอลัมน์ Status ที่มาจาก docstatus
		// และแสดงเฉพาะ status ที่เราต้องการ
	}
};

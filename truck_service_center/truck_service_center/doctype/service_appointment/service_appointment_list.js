frappe.listview_settings["Service Appointment"] = {
	onload(listview) {
		const route = frappe.get_route();
		const isServiceAppointment = route && route[1] === "Service Appointment";
		const isCalendar = route && route[2] === "Calendar";

		if (isServiceAppointment && !isCalendar) {
			frappe.set_route("List", "Service Appointment", "Calendar", "default");
		}
	},
	
	add_fields: ["status", "docstatus"],
	
	get_indicator(doc) {
		const status_colors = {
			"Scheduled": "gray",
			"Confirmed": "blue",
			"In Progress": "orange",
			"Completed": "green",
			"Cancelled": "red",
			"No Show": "darkgray"
		};
		
		const status = doc.status || "Scheduled";
		const color = status_colors[status] || "gray";
		
		return [__(status), color, "status,=," + status];
	},
	
	formatters: {
		status(value) {
			// แสดง status ที่กำหนดเองแทน docstatus
			return value || "Scheduled";
		}
	}
};


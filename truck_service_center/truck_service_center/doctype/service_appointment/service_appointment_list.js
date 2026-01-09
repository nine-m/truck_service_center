frappe.listview_settings["Service Appointment"] = {
	onload(listview) {
		const route = frappe.get_route();
		const isServiceAppointment = route && route[1] === "Service Appointment";
		const isCalendar = route && route[2] === "Calendar";

		if (isServiceAppointment && !isCalendar) {
			frappe.set_route("List", "Service Appointment", "Calendar", "default");
		}
	},
};

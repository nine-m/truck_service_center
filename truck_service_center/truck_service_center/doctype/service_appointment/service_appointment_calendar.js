frappe.views.calendar["Service Appointment"] = {
	field_map: {
		start: "appointment_start",
		end: "appointment_end",
		title: "license_plate",
		allDay: "all_day"
	},
	fields: [
		"name",
		"appointment_date",
		"appointment_start",
		"appointment_end",
		"all_day",
		"license_plate",
		"status",
		"service_type",
	],
	get_events_method: "frappe.desk.calendar.get_events",
	order_by: "appointment_date asc",
	prepare_events(events) {
		// Force timed events when both datetimes are present; otherwise render as all-day.
		const basePrepare = frappe.views.Calendar.prototype.prepare_events;
		const normalized = (events || []).map((event) => {
			const hasTimeRange = Boolean(event.appointment_start && event.appointment_end);
			event.__has_time_range = hasTimeRange;
			if (!hasTimeRange) {
				event.all_day = 1;
				if (event.appointment_date) {
					event.appointment_start = event.appointment_date;
					event.appointment_end = event.appointment_date;
				}
			} else {
				event.all_day = 0;
			}
			return event;
		});

		return basePrepare.call(this, normalized).map((event) => {
			const hasTimeRange = Boolean(event.__has_time_range);
			event.allDay = hasTimeRange ? false : true;

			// Explicitly paint color by status for both timed and all-day events.
			const statusColor = this.get_css_class ? this.get_css_class(event) : null;
			if (statusColor) {
				const bg = hasTimeRange ? statusColor : lighten(statusColor, 0.2);
				const fg = frappe.ui.color.get_contrast_color(bg);
				event.backgroundColor = bg;
				event.borderColor = bg;
				event.textColor = fg;
				event.color = bg;
			}

			// Compose title with plate, service type, status for clearer calendar labels.
			const titleParts = [];
			if (event.license_plate) titleParts.push(event.license_plate);
			if (event.service_type) titleParts.push(event.service_type);
			if (event.status) titleParts.push(event.status);
			event.title = titleParts.join(" · ") || event.name;
			delete event.__has_time_range;
			return event;
		});
	},
	get_css_class: function(event) {
		const status = event.status || "";
		const colors = {
			"Scheduled": "#0d6efd",
			"Confirmed": "#0d6efd",
			"In Progress": "#fd7e14",
			"Completed": "#198754",
			"Cancelled": "#dc3545",
			"No Show": "#6c757d",
		};
		return colors[status] || "#adb5bd";
	}
};

// Simple hex color lighten utility (factor 0-1).
function lighten(hex, factor = 0.2) {
	const num = parseInt(hex.slice(1), 16);
	const r = Math.min(255, Math.floor(((num >> 16) & 0xff) + 255 * factor));
	const g = Math.min(255, Math.floor(((num >> 8) & 0xff) + 255 * factor));
	const b = Math.min(255, Math.floor((num & 0xff) + 255 * factor));
	return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}

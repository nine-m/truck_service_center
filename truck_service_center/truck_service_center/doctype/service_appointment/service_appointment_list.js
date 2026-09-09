frappe.listview_settings["Service Appointment"] = {
	onload(listview) {
		const route = frappe.get_route();
		const isServiceAppointment = route && route[1] === "Service Appointment";
		const isCalendar = route && route[2] === "Calendar";

		if (isServiceAppointment && !isCalendar) {
			frappe.set_route("List", "Service Appointment", "Calendar", "default");
		}
	},
	
	// ปฏิทินคือหน้าหลักของนัดหมาย — ซ่อนปุ่ม header ที่ไม่มีผลกับมุมมองปฏิทิน
	// (sort ไม่มีผลเพราะปฏิทินจัดตามวันเอง, Default Layouts เป็นเรื่องคอลัมน์ของ List view)
	// ต้องเป็น hook refresh ไม่ใช่ onload: CalendarView override setup_view เป็นค่าว่าง
	// ทำให้ settings.onload ไม่ถูกเรียกบนปฏิทิน แต่ settings.refresh ยังถูกเรียกผ่าน BaseList.refresh
	refresh(listview) {
		if (listview.view_name !== "Calendar") {
			return;
		}
		listview.page.wrapper.find(".sort-selector").hide();
		// เมนู layout ถูกสร้าง async หลังโหลด list_layout bundle — รอ promise ของมันก่อนค่อยซ่อน
		const hide_layout_menu = () => {
			const selector = `.inner-group-button[data-label="${encodeURIComponent(
				__("Default Layouts")
			)}"]`;
			listview.page.wrapper.find(selector).hide();
		};
		if (listview.list_filter && listview.list_filter.setup_promise) {
			listview.list_filter.setup_promise.then(hide_layout_menu);
		}
		hide_layout_menu();
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


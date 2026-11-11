frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["TSC Bay Usage Today"] = {
	method: "truck_service_center.truck_service_center.dashboard_chart_source.tsc_bay_usage_today.tsc_bay_usage_today.get",
	filters: [
		{
			// ว่าง = ทุกสาขาที่ผู้ใช้เห็นได้ — ช่องจอดเป็นของสาขาเดียว แท่งจึงไม่ปนกันอยู่แล้ว
			fieldname: "branch",
			label: __("สาขา"),
			fieldtype: "Link",
			options: "Service Branch",
			default: frappe.defaults.get_user_default("Service Branch")
		}
	]
};

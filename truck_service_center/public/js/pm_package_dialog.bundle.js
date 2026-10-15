// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

// หน้าต่างแนะนำแพ็คเกจ PM ตามระยะ — ใช้ร่วมกันใน Service Order, Repair Quotation, Service Appointment
// (ทั้งสามฟอร์มมีตาราง service_packages และ handler "service_package" ที่ดึงบริการ/อะไหล่ของแพ็คเกจเองอยู่แล้ว)
// โหลดผ่าน app_include_js ใน hooks.py ครั้งเดียว ไม่ใช้ doctype_js เพราะจะถูกโหลดซ้ำทุกฟอร์ม
// แก้ไฟล์นี้แล้วต้อง bench build --app truck_service_center

frappe.provide("truck_service_center.pm");

const PM_PACKAGE_METHOD =
	"truck_service_center.truck_service_center.doctype.service_package.service_package.get_pm_packages";

// ฟิลด์ fetch_from ของแถวแพ็คเกจ — set_value จากโค้ดไม่ทำให้ Frappe fetch ให้ (fetch เกิดตอนพิมพ์ในช่องเท่านั้น)
// จึงเติมจากผลที่ get_pm_packages ส่งมาเอง ไม่งั้นชื่อ/ราคาในตารางว่างจนกว่าจะบันทึก
const PM_PACKAGE_ROW_FIELDS = [
	"package_code",
	"package_name",
	"package_rate",
	"discount_percent",
	"repair_time_hours",
];

truck_service_center.pm.add_button = function (frm) {
	if (frm.doc.docstatus !== 0 || !frm.has_perm("write")) return;

	frm.add_custom_button(__("แนะนำแพ็คเกจ PM"), function () {
		truck_service_center.pm.show_package_dialog(frm);
	});
};

truck_service_center.pm.show_package_dialog = function (frm) {
	let packages = [];
	let request_seq = 0;

	let unit_label = function (unit) {
		return unit === "hours" ? __("ชม.") : __("กม.");
	};

	let reading_hint = __("ใส่เลขกลมตามรอบ PM เช่น รถเข้ามาที่ 325,759 กม. ให้ใส่ 330000");
	if (frm.doc.current_mileage) {
		reading_hint +=
			"<br>" +
			__("เลขไมล์ในเอกสาร: {0} กม.", [format_number(frm.doc.current_mileage, null, 0)]);
	}

	let dialog = new frappe.ui.Dialog({
		title: __("แนะนำแพ็คเกจ PM"),
		size: "large",
		fields: [
			{
				fieldname: "pm_truck_type",
				fieldtype: "Link",
				options: "PM Truck Type",
				label: __("รหัสประเภทรถ PM"),
				reqd: 1,
				onchange: () => refresh_results(),
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "unit",
				fieldtype: "Select",
				label: __("วัดจาก"),
				options: [
					{ label: __("กิโลเมตร"), value: "km" },
					{ label: __("ชั่วโมงทำงาน"), value: "hours" },
				],
				default: "km",
				reqd: 1,
				onchange: () => refresh_results(),
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "reading",
				fieldtype: "Int",
				label: __("เลขไมล์ / ชั่วโมงทำงาน"),
				description: reading_hint,
				reqd: 1,
				onchange: () => refresh_results(),
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "search_button",
				fieldtype: "Button",
				label: __("ค้นหาแพ็คเกจที่ครบระยะ"),
				click: () => search_packages(),
			},
			{ fieldtype: "Section Break", label: __("แพ็คเกจที่ครบระยะ") },
			{ fieldname: "results", fieldtype: "HTML" },
		],
		primary_action_label: __("เพิ่มแพ็คเกจที่เลือก"),
		primary_action: function () {
			add_selected_packages();
		},
	});

	let $results = dialog.fields_dict.results.$wrapper;

	let render_message = function (message) {
		$results.html(
			`<div class="text-muted" style="padding: var(--padding-sm) 0;">${message}</div>`
		);
	};

	let existing_packages = function () {
		return new Set(
			(frm.doc.service_packages || []).map((row) => row.service_package).filter(Boolean)
		);
	};

	let render_packages = function (unit, reading) {
		if (!packages.length) {
			render_message(
				__("ไม่พบแพ็คเกจที่ครบระยะ {0} {1} — ตรวจสอบว่าปัดเลขให้ตรงระยะ PM แล้ว", [
					format_number(reading, null, 0),
					unit_label(unit),
				])
			);
			return;
		}

		let added = existing_packages();
		let rows = packages
			.map(function (pkg) {
				let is_added = added.has(pkg.name);
				let name = frappe.utils.escape_html(pkg.name);
				return `
					<tr>
						<td style="width: 2.5rem;">
							<input type="checkbox" class="pm-package-check" data-package="${name}"
								${is_added ? "disabled" : "checked"}>
						</td>
						<td>${frappe.utils.escape_html(pkg.package_code || pkg.name)}</td>
						<td>
							${frappe.utils.escape_html(pkg.package_name || "")}
							${is_added ? `<span class="indicator-pill grey">${__("เพิ่มแล้ว")}</span>` : ""}
						</td>
						<td class="text-right">${__("ทุก {0} {1}", [
							format_number(pkg.pm_interval, null, 0),
							unit_label(unit),
						])}</td>
						<td class="text-right">${format_currency(pkg.package_rate)}</td>
					</tr>`;
			})
			.join("");

		$results.html(`
			<div class="table-responsive">
				<table class="table table-bordered table-sm" style="margin-bottom: 0;">
					<thead>
						<tr>
							<th></th>
							<th>${__("รหัสแพ็คเกจ")}</th>
							<th>${__("ชื่อแพ็คเกจ")}</th>
							<th class="text-right">${__("รอบ")}</th>
							<th class="text-right">${__("ราคา")}</th>
						</tr>
					</thead>
					<tbody>${rows}</tbody>
				</table>
			</div>
			<div class="text-muted small" style="margin-top: var(--margin-sm);">
				${__('ติ๊กออกรายการที่ไม่ต้องการทำ แล้วกด "เพิ่มแพ็คเกจที่เลือก"')}
			</div>`);
	};

	let render_prompt = function () {
		render_message(
			__('เลือกรหัสประเภทรถ ใส่เลขไมล์/ชั่วโมงทำงาน แล้วกดปุ่ม "ค้นหาแพ็คเกจที่ครบระยะ"')
		);
	};

	// ผลค้นหาเก่าใช้ไม่ได้ทันทีที่ผู้ใช้เริ่มแก้ค่า — ไม่งั้นแก้เลขแล้วกด "เพิ่ม" เลย
	// จะได้แพ็คเกจของเลขเดิม (onchange ของช่องตัวเลขยิงตอนออกจากช่องเท่านั้น)
	let invalidate_results = function () {
		packages = [];
		request_seq++;
		render_prompt();
	};

	// ใช้ลำดับคำขอทิ้งผลที่มาช้ากว่าคำขอล่าสุด (ปุ่มกับ onchange ยิงซ้อนกันได้)
	let search_packages = function () {
		let values = dialog.get_values(true);
		let reading = cint(values.reading);
		packages = [];

		if (!values.pm_truck_type || reading <= 0) {
			request_seq++;
			render_message(__("กรุณาเลือกรหัสประเภทรถและใส่เลขไมล์/ชั่วโมงทำงานให้ครบก่อนค้นหา"));
			return;
		}

		let seq = ++request_seq;
		render_message(__("กำลังค้นหา..."));
		frappe
			.call({
				method: PM_PACKAGE_METHOD,
				args: { pm_truck_type: values.pm_truck_type, reading: reading, unit: values.unit },
			})
			.then(function (r) {
				if (seq !== request_seq) return;
				packages = r.message || [];
				render_packages(values.unit, reading);
			});
	};

	// กด Enter / ออกจากช่อง / เปลี่ยนตัวเลือก ก็ค้นหาให้เอง นอกเหนือจากปุ่ม
	let refresh_results = frappe.utils.debounce(search_packages, 300);

	let add_selected_packages = function () {
		let selected = new Set(
			$results
				.find(".pm-package-check:checked:not(:disabled)")
				.map(function () {
					return $(this).attr("data-package");
				})
				.get()
		);
		if (!selected.size) {
			frappe.show_alert({ message: __("ยังไม่ได้เลือกแพ็คเกจ"), indicator: "orange" });
			return;
		}

		let added = existing_packages();
		let count = 0;
		packages.forEach(function (pkg) {
			if (!selected.has(pkg.name) || added.has(pkg.name)) return;

			let row = frm.add_child("service_packages");
			PM_PACKAGE_ROW_FIELDS.forEach(function (fieldname) {
				if (frappe.meta.has_field(row.doctype, fieldname)) row[fieldname] = pkg[fieldname];
			});
			// set_value ยิง handler "service_package" ของฟอร์ม ให้ดึงบริการและอะไหล่ของแพ็คเกจเอง
			frappe.model.set_value(row.doctype, row.name, "service_package", pkg.name);
			count++;
		});

		frm.refresh_field("service_packages");
		dialog.hide();
		frappe.show_alert({
			message: __("เพิ่ม {0} แพ็คเกจ PM เรียบร้อย", [count]),
			indicator: "green",
		});
	};

	dialog.show();
	render_prompt();
	dialog.fields_dict.reading.$input.on("input", invalidate_results);

	// รถที่ตั้งรหัสประเภท PM ไว้ — เติมให้ ผู้ใช้เปลี่ยนเองได้
	if (frm.doc.vehicle) {
		frappe.db.get_value("Vehicle", frm.doc.vehicle, "pm_truck_type").then(function (r) {
			let pm_truck_type = r.message && r.message.pm_truck_type;
			if (pm_truck_type && !dialog.get_value("pm_truck_type")) {
				dialog.set_value("pm_truck_type", pm_truck_type);
			}
		});
	}
};

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
	],
	get_events_method:
		"truck_service_center.truck_service_center.doctype.service_appointment.service_appointment.get_calendar_events",
	order_by: "appointment_date asc",
	capacity_method:
		"truck_service_center.truck_service_center.doctype.service_appointment.service_appointment.get_capacity_range",

	// config object ถูก $.extend ลง instance ของ frappe.views.Calendar ทุก key จึงกลายเป็น
	// method ของ instance และ override ของเดิมได้ (วิธีเดียวกับ prepare_events ด้านล่าง)
	setup_options(defaults) {
		// เรียกของเดิมก่อน เพื่อคง dateClick/select/eventClick ของ Frappe ไว้ครบ
		frappe.views.Calendar.prototype.setup_options.call(this, defaults);

		const me = this;
		this.capacity_days = {};
		tsc_inject_capacity_css();

		Object.assign(this.cal_options, {
			datesSet: function(info) {
				// FullCalendar ให้ end แบบ exclusive จึงถอยหนึ่งวัน
				// ใช้ startStr/endStr ไม่ใช่ Date object — toISOString() จะเลื่อนไปหนึ่งวัน
				// ใน timezone ที่ offset เป็นบวก (ไทย +7)
				me.load_capacity(
					info.startStr.slice(0, 10),
					frappe.datetime.add_days(info.endStr.slice(0, 10), -1)
				);
			},
			dayCellDidMount: function(arg) {
				me.paint_capacity_cell(arg.el, tsc_cell_date(arg), ".fc-daygrid-day-top");
			},
			dayHeaderDidMount: function(arg) {
				// เฉพาะมุมมองสัปดาห์/วัน — หัวคอลัมน์ของมุมมองเดือนเป็นชื่อวัน ไม่ใช่วันที่
				if (!arg.view || !arg.view.type || arg.view.type.indexOf("timeGrid") !== 0) return;
				me.paint_capacity_cell(arg.el, tsc_cell_date(arg), null);
			},
			dayCellClassNames: function(arg) {
				return tsc_capacity_cell_class(me.capacity_days[tsc_ymd(arg.date)]);
			}
		});
	},

	load_capacity(start, end, force) {
		if (!start || !end) return;

		// datesSet ยิงหลายครั้งต่อการเปลี่ยนมุมมองหนึ่งครั้ง — กัน request ซ้อนด้วย key ช่วงวัน
		const key = `${start}|${end}`;
		if (!force && this._capacity_range_key === key) return;
		this._capacity_range_key = key;

		const me = this;
		frappe.xcall(this.capacity_method, { start: start, end: end })
			.then(function(data) {
				if (!data || !data.days) return;
				me.capacity_days = Object.assign(me.capacity_days || {}, data.days);
				// ห้ามเรียก fullCalendar.render()/setOption ที่นี่เด็ดขาด — จะยิง datesSet
				// ซ้ำแล้ววนไม่รู้จบ แปะลง cell ที่มีอยู่ด้วย jQuery แทน
				me.repaint_capacity();
			})
			.catch(function() {
				// ปล่อย key ทิ้ง เพื่อให้การเลื่อนกลับมาที่ช่วงเดิมลองใหม่ได้
				if (me._capacity_range_key === key) me._capacity_range_key = null;
			});
	},

	repaint_capacity() {
		if (!this.$cal) return;

		const me = this;
		// cell ที่ mount ก่อนข้อมูลมาถึงต้องพึ่งรอบนี้ ส่วน cell ที่ mount หลังข้อมูลมาแล้ว
		// (สลับเดือน / ซ่อนเสาร์อาทิตย์) ได้จาก dayCellDidMount
		this.$cal.find("td.fc-daygrid-day[data-date]").each(function() {
			me.paint_capacity_cell(this, $(this).attr("data-date"), ".fc-daygrid-day-top");
		});
		// มุมมองเดือนไม่มี data-date บนหัวคอลัมน์ selector จึงคัดเฉพาะ timeGrid ให้เอง
		this.$cal.find("th.fc-col-header-cell[data-date]").each(function() {
			me.paint_capacity_cell(this, $(this).attr("data-date"), null);
		});
	},

	paint_capacity_cell(el, date, host_selector) {
		if (!el || !date) return;

		const $el = $(el);
		const day = (this.capacity_days || {})[date];

		// tint ต้องแปะเองด้วย เพราะ dayCellClassNames ถูกเรียกตอน render เท่านั้น
		// cell ที่ render ไปก่อนข้อมูลมาถึงจะไม่มีวันได้ class จาก hook นั้นเลย
		const classes = tsc_capacity_cell_class(day);
		$el.toggleClass("tsc-cap-full-day", classes.indexOf("tsc-cap-full-day") !== -1);

		// ห้ามแทนตัว cell — dateClick ของ Frappe หา td[data-date] จึงได้แค่ append ข้างใน
		const $host = host_selector ? $el.find(host_selector).first() : $el;
		if (!$host.length) return;

		// painter ต้อง idempotent ไม่งั้นสลับเดือนไป-กลับแล้ว badge จะซ้อนกันหลายอัน
		$host.find(".tsc-cap").remove();
		if (host_selector) $host.addClass("tsc-cap-host");

		// ยังไม่มีข้อมูลก็ไม่แปะอะไร กันกะพริบระหว่างรอ response
		if (!day) return;

		$host.append(tsc_capacity_badge_html(day, date));
		this.bind_capacity_click();
	},

	bind_capacity_click() {
		// ผูกที่ $wrapper (ชั้นนอกสุด) ไม่ใช่ $cal — FullCalendar สร้าง DOM ข้างในใหม่ทุกครั้ง
		// ที่เปลี่ยนมุมมอง delegated handler จึงต้องอยู่บนชั้นที่ไม่ถูกรื้อ
		if (this._capacity_click_bound || !this.$wrapper) return;
		this._capacity_click_bound = true;

		const me = this;
		// FullCalendar ตัดสิน dateClick จาก pointer gesture (mousedown→mouseup) ไม่ใช่ event click
		// การ stopPropagation ตอน click จึงสายเกินไป ต้องสกัดตั้งแต่ mousedown
		this.$wrapper.on("mousedown", ".tsc-cap", function(e) {
			e.stopPropagation();
			e.preventDefault();
		});
		this.$wrapper.on("click", ".tsc-cap", function(e) {
			e.stopPropagation();
			e.preventDefault();
			me.show_capacity_detail($(this).attr("data-date"));
		});
	},

	show_capacity_detail(date) {
		const day = (this.capacity_days || {})[date];
		if (!day) return;

		frappe.msgprint({
			title: __("ความจุช่องจอด — {0}", [date]),
			indicator: "blue",
			message: tsc_capacity_detail_html(day)
		});
	},

	refresh() {
		// Frappe เรียก refresh() ตอนกลับมาจากฟอร์ม ซึ่งเป็นแค่ refetchEvents()
		// จึงไม่ยิง datesSet — ถ้าไม่ดึงความจุใหม่เอง badge จะค้างเป็นค่าก่อนแก้เอกสาร
		frappe.views.Calendar.prototype.refresh.call(this);

		const view = this.fullCalendar && this.fullCalendar.view;
		if (!view) return;
		this.load_capacity(tsc_ymd(view.activeStart), tsc_ymd(new Date(view.activeEnd - 86400000)), true);
	},

	prepare_events(events) {
		// นัดที่ระบุเวลาไว้ = event มีเวลา ส่วนนัดที่ไม่ระบุเวลา (all_day) = ทั้งวัน
		// ต้องดู all_day ด้วย เพราะนัดที่ไม่ระบุเวลาจะมี start = end = เที่ยงคืนของวันนั้น
		// ซึ่งถ้าดูแค่ว่ามีค่าไหม จะกลายเป็น event ยาว 0 นาทีตอนเที่ยงคืน
		const basePrepare = frappe.views.Calendar.prototype.prepare_events;
		const normalized = (events || []).map((event) => {
			const hasTimeRange = Boolean(
				event.appointment_start && event.appointment_end && !cint(event.all_day)
			);
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

			// Compose title with plate and status for clearer calendar labels.
			const titleParts = [];
			if (event.license_plate) titleParts.push(event.license_plate);
			if (event.status) titleParts.push(event.status);
			event.title = titleParts.join(" · ") || event.name;
			delete event.__has_time_range;
			return event;
		});
	},
	get_css_class: function(event) {
		const status = event.status || "";
		// โทนสีเดียวกับ get_indicator ใน service_appointment_list.js
		const colors = {
			"Scheduled": "#6c757d",
			"Confirmed": "#0d6efd",
			"In Progress": "#fd7e14",
			"Completed": "#198754",
			"Cancelled": "#dc3545",
			"No Show": "#343a40",
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

// ---------------------------------------------------------------------------
// ตัวช่วยระดับไฟล์สำหรับ badge ความจุ
//
// badge class map ซ้ำกับ bay_status_badge ใน service_appointment.js โดยเจตนา —
// สองไฟล์เป็น script คนละตัวที่ถูก eval แยกกัน ไม่มี module ให้ import ร่วม การจะแชร์
// ต้องทำเป็น bundle ซึ่งแปลว่าต้อง bench build ทุกครั้งที่แก้ (repo นี้เลี่ยงไว้)
// ---------------------------------------------------------------------------

function tsc_ymd(date) {
	// ห้ามใช้ toISOString() — FullCalendar ให้ Date ที่ local getters ตรงกับวันในปฏิทิน
	// การแปลงเป็น UTC จะเลื่อนไปหนึ่งวันใน timezone ที่ offset เป็นบวก (ไทย +7)
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const day = String(date.getDate()).padStart(2, "0");
	return `${year}-${month}-${day}`;
}

function tsc_cell_date(arg) {
	// data-date ที่ FullCalendar เขียนไว้เชื่อถือได้ที่สุด เหลือ tsc_ymd ไว้เป็นทางสำรอง
	const attr = arg.el && arg.el.getAttribute ? arg.el.getAttribute("data-date") : null;
	return attr || (arg.date ? tsc_ymd(arg.date) : null);
}

function tsc_fmt_hours(hours) {
	// ตัด .00 ทิ้ง — ช่องปฏิทินแคบ "8 ชม." อ่านง่ายกว่า "8.00 ชม."
	return String(parseFloat(flt(hours, 2).toFixed(2)));
}

function tsc_status_badge(status) {
	const classes = {
		"ว่าง": "badge-success",
		"ใกล้เต็ม": "badge-warning",
		"เต็ม": "badge-danger",
		"ปิดทำการ": "badge-secondary"
	};
	return classes[status] || "badge-secondary";
}

function tsc_capacity_cell_class(day) {
	// ระบายพื้นหลังเฉพาะวันที่เต็มจริง ๆ — วันปิดทำการมีป้าย "ปิด" บอกอยู่แล้ว และวันอาทิตย์
	// ถูก Frappe ระบายให้ก่อนแล้ว (.fc-theme-standard td.fc-day-sun) ถ้าระบายอีกจะทึบเกิน
	if (!day || !day.summary) return [];
	return day.summary.status === "เต็ม" && !day.summary.is_closed ? ["tsc-cap-full-day"] : [];
}


function tsc_capacity_badge_html(day, date) {
	const summary = day.summary || {};
	const over = flt(summary.over);

	// ปฏิทินหนึ่งเดือนมีสามสิบกว่าช่อง ถ้าทุกช่องเป็น pill ทึบสีเข้มจะกลายเป็นลายพราง
	// อ่านไม่ออกว่าวันไหนต้องสนใจ จึงให้วันปกติเป็นตัวเลขจาง ๆ แล้วใส่สีเฉพาะวันที่มีปัญหา
	let mod;
	let text;
	if (summary.has_bays === false) {
		mod = "tsc-cap--none";
		text = "—";
	} else if (summary.is_closed) {
		mod = "tsc-cap--closed";
		text = "ปิด";
	} else if (summary.status === "เต็ม") {
		mod = "tsc-cap--full";
		text = `${tsc_fmt_hours(summary.booked)}/${tsc_fmt_hours(summary.cap)}`;
	} else if (summary.status === "ใกล้เต็ม") {
		mod = "tsc-cap--near";
		text = `${tsc_fmt_hours(summary.booked)}/${tsc_fmt_hours(summary.cap)}`;
	} else {
		mod = "tsc-cap--free";
		text = `${tsc_fmt_hours(summary.booked)}/${tsc_fmt_hours(summary.cap)}`;
	}

	const title = frappe.utils.escape_html(tsc_capacity_tooltip(day));
	let html = `<span class="tsc-cap ${mod}" role="button" tabindex="0"`;
	html += ` data-date="${frappe.utils.escape_html(date)}" title="${title}">`;
	html += frappe.utils.escape_html(text);
	// จองเกินต้องแดงเสมอ แม้สถานะรวมจะยังว่าง (ช่องหนึ่งล้นขณะที่อีกช่องยังโล่ง)
	if (over > 0) {
		html += `<b class="tsc-cap-over">+${frappe.utils.escape_html(tsc_fmt_hours(over))}</b>`;
	}
	html += "</span>";

	return html;
}


function tsc_capacity_tooltip(day) {
	// native tooltip รองรับ \n อยู่แล้ว ไม่ต้องพึ่ง JS tooltip เพิ่ม
	const summary = day.summary || {};
	const lines = [];

	// บรรทัดแรกอธิบายตัวเลขย่อในช่อง ("0/48" คืออะไร) แล้วค่อยลงรายละเอียดรายช่องจอด
	if (summary.has_bays === false) {
		lines.push("ยังไม่มีช่องจอดซ่อมที่เปิดใช้งาน");
	} else {
		let head = `ใช้ไป ${tsc_fmt_hours(summary.booked)}/${tsc_fmt_hours(summary.cap)} ชม.`;
		head += ` · เหลือ ${tsc_fmt_hours(summary.free)} ชม.`;
		if (flt(summary.over) > 0) head += ` · เกิน ${tsc_fmt_hours(summary.over)} ชม.`;
		lines.push(head);
	}
	if (summary.day_note) lines.push(summary.day_note);
	(day.bays || []).forEach(function(bay) {
		let line = `${bay.bay_name || bay.bay} · ${tsc_fmt_hours(bay.booked)}/${tsc_fmt_hours(bay.cap)} ชม. · ${bay.status}`;
		if (bay.is_closed && bay.reason) line += ` (${bay.reason})`;
		lines.push(line);
	});

	return lines.join("\n");
}

function tsc_capacity_detail_html(day) {
	const summary = day.summary || {};
	let html = "";

	if (summary.day_note) {
		html += `<p class="text-muted">${frappe.utils.escape_html(summary.day_note)}</p>`;
	}

	html += `<p><b>${tsc_fmt_hours(summary.booked)}/${tsc_fmt_hours(summary.cap)} ชม.</b> `;
	html += `<span class="badge ${tsc_status_badge(summary.status)}">${frappe.utils.escape_html(summary.status || "")}</span>`;
	if (flt(summary.over) > 0) {
		html += ` <b class="text-danger">เกิน +${tsc_fmt_hours(summary.over)}</b>`;
	}
	html += "</p>";

	if (!(day.bays || []).length) {
		html += '<p class="text-muted">ยังไม่มีช่องจอดซ่อมที่เปิดใช้งาน</p>';
		return html;
	}

	html += '<table class="table table-bordered" style="margin-top: 5px;">';
	html += "<thead><tr><th>ช่องจอด</th><th>หลุมซ่อม</th><th>จองแล้ว/รับได้ (ชม.)</th><th>สถานะ</th></tr></thead><tbody>";
	(day.bays || []).forEach(function(bay) {
		const reason = bay.is_closed && bay.reason ? ` <small class="text-muted">(${frappe.utils.escape_html(bay.reason)})</small>` : "";
		html += "<tr>";
		html += `<td><strong>${frappe.utils.escape_html(bay.bay_name || bay.bay)}</strong></td>`;
		html += `<td>${bay.has_pit ? "มี" : "-"}</td>`;
		html += `<td>${tsc_fmt_hours(bay.booked)} / ${tsc_fmt_hours(bay.cap)}</td>`;
		html += `<td><span class="badge ${tsc_status_badge(bay.status)}">${frappe.utils.escape_html(bay.status)}</span>${reason}</td>`;
		html += "</tr>";
	});
	html += "</tbody></table>";

	return html;
}

function tsc_inject_capacity_css() {
	if (document.getElementById("tsc-capacity-css")) return;

	const style = document.createElement("style");
	style.id = "tsc-capacity-css";
	style.textContent = `
		/* ต้องเป็น positioned element และ z-index สูงกว่าเลเยอร์ของมุมมองเดือน ไม่งั้นคลิกไม่โดน:
		   .fc-daygrid-day-number เป็น position:relative z-index:4 และ .fc-daygrid-day-events
		   เป็น position:absolute โดยมี .fc-daygrid-event z-index:6 — badge ที่เป็น static
		   (z-index: auto) จะถูกสองเลเยอร์นี้บังรับคลิกไปหมด มุมมองสัปดาห์/วันไม่มีปัญหานี้
		   เพราะ badge อยู่บนหัวคอลัมน์ซึ่งไม่มีเลเยอร์พวกนี้เลย */
		.tsc-cap {
			position: relative;
			z-index: 7;
			cursor: pointer;
			font-size: 12px;
			font-weight: 600;
			line-height: 1;
			white-space: nowrap;
			font-variant-numeric: tabular-nums;
			padding: 3px 6px;
			border-radius: 6px;
			/* .fc-daygrid-day-top เป็น flex และ align-items ปริยายคือ stretch — pill จะถูกยืด
			   สูงเท่าเลขวัน (ที่มี padding 4px) แต่ตัวอักษรยังเกาะขอบบน ดูเหมือนลอย
			   align-self: center กันการยืด ส่วน inline-flex + align-items จัดตัวเลขให้อยู่กลาง
			   ในทุกบริบท รวมหัวคอลัมน์ของมุมมองสัปดาห์/วันที่ไม่ได้เป็น flex item */
			display: inline-flex;
			align-items: center;
			align-self: center;
		}
		/* Frappe บังคับ .fc-daygrid-day-top เป็น flex-direction: row (margin ซ้าย 10px)
		   margin-left:auto จึงดันตัวเลขไปชิดขวาสุด ไม่ไปเบียดเลขวันที่อยู่ซ้าย */
		.tsc-cap-host .tsc-cap { margin-left: auto; margin-right: 8px; }
		.tsc-cap-host { flex-wrap: wrap; }
		.tsc-cap:hover { box-shadow: 0 0 0 1px var(--gray-400, #b8bfc7); }
		/* พื้นหลังอ่อนพอให้อ่านออกทุกช่อง แต่ไม่ทึบจนกลบ event ในช่องเดียวกัน
		   ไล่ความเข้มตามความเร่งด่วน สายตาจึงไปหยุดที่วันใกล้เต็ม/เต็มก่อน */
		.tsc-cap--free { color: var(--green-700, #0f7a4d); background: var(--green-100, #d3f7e4); }
		.tsc-cap--near { color: var(--orange-700, #96430f); background: var(--orange-100, #ffe8cd); }
		.tsc-cap--full { color: var(--red-700, #a31f1f); background: var(--red-100, #ffdcdc); }
		.tsc-cap--closed, .tsc-cap--none { color: var(--gray-600, #6a7581); background: var(--gray-100, #f4f5f6); }
		.tsc-cap-over { color: var(--red-700, #a31f1f); margin-left: 4px; }
		.tsc-cap-full-day { background: var(--red-50, #fff5f5); }
		/* หัวคอลัมน์ของมุมมองสัปดาห์/วัน — วางเป็นบรรทัดใหม่ใต้ชื่อวัน ไม่ต้องดันชิดขวา */
		th.fc-col-header-cell .tsc-cap { margin-top: 2px; }
	`;
	document.head.appendChild(style);
}

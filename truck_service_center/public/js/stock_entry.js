// Copyright (c) 2026, SVL Technology Co. Ltd. and contributors
// For license information, please see license.txt

// ขั้นอนุมัติใบเบิกอะไหล่ของใบสั่งงาน — ปุ่มเรียก endpoint เดียวกับพอร์ทัลช่าง
// ด่านจริงอยู่ฝั่ง server (can_approve_requisition / validate_requisition_approved)

const TSC_PORTAL_API = "truck_service_center.api.technician_portal.";

const TSC_REJECT_PRESETS = [
	"จำนวนเกินที่ใช้จริง",
	"ผิดรายการ / ผิดรุ่น",
	"ยังมีของเหลือในรถ",
	"ให้ตรวจสอบอาการก่อนเบิก",
];

frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		if (!frm.doc.custom_service_order) return;

		tsc_show_approval_intro(frm);

		if (frm.doc.docstatus !== 0 || frm.doc.custom_approval_status !== "Pending") return;

		frappe.call({
			method: TSC_PORTAL_API + "get_requisition_actions",
			args: { stock_entry: frm.doc.name },
			callback(r) {
				if (!r.message || !r.message.can_approve) return;

				frm.add_custom_button(__("อนุมัติใบเบิก"), () => tsc_approve(frm)).addClass(
					"btn-primary"
				);
				frm.add_custom_button(__("ไม่อนุมัติ"), () => tsc_reject(frm));
			},
		});
	},
});

function tsc_show_approval_intro(frm) {
	const status = frm.doc.custom_approval_status;
	const by = frappe.utils.escape_html(frm.doc.custom_approved_by_name || "");

	if (status === "Pending") {
		frm.set_intro(
			__("ใบเบิกนี้รอหัวหน้างานกลุ่มอนุมัติ — ยัง Submit ไม่ได้ (ผู้ขอเบิก: {0})", [
				frappe.utils.escape_html(frm.doc.custom_created_by_name || "-"),
			]),
			"orange"
		);
	} else if (status === "Rejected") {
		frm.set_intro(
			__("ไม่อนุมัติโดย {0} — เหตุผล: {1}", [
				by,
				frappe.utils.escape_html(frm.doc.custom_rejection_reason || "-"),
			]),
			"red"
		);
	} else if (status === "Approved" && frm.doc.docstatus === 0) {
		frm.set_intro(__("อนุมัติแล้วโดย {0} — Submit ได้", [by]), "green");
	}
}

function tsc_approve(frm) {
	frappe.confirm(__("อนุมัติใบเบิก {0}?", [frm.doc.name]), () => {
		frappe.call({
			method: TSC_PORTAL_API + "approve_requisition",
			args: { stock_entry: frm.doc.name },
			freeze: true,
			callback(r) {
				if (!r.exc) {
					frappe.show_alert({ message: __("อนุมัติแล้ว"), indicator: "green" });
					frm.reload_doc();
				}
			},
		});
	});
}

function tsc_reject(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("ไม่อนุมัติใบเบิก {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "preset",
				fieldtype: "Select",
				label: __("เหตุผลสำเร็จรูป"),
				options: [""].concat(TSC_REJECT_PRESETS),
				change() {
					const value = dialog.get_value("preset");
					if (value) dialog.set_value("reason", value);
				},
			},
			{ fieldname: "reason", fieldtype: "Small Text", label: __("เหตุผล"), reqd: 1 },
		],
		primary_action_label: __("ไม่อนุมัติ"),
		primary_action(values) {
			frappe.call({
				method: TSC_PORTAL_API + "reject_requisition",
				args: { stock_entry: frm.doc.name, reason: values.reason },
				freeze: true,
				callback(r) {
					if (!r.exc) {
						dialog.hide();
						frappe.show_alert({ message: __("ไม่อนุมัติแล้ว"), indicator: "orange" });
						frm.reload_doc();
					}
				},
			});
		},
	});
	dialog.show();
}

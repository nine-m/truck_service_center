frappe.listview_settings['Service Type'] = {
	onload: function(listview) {
		listview.page.add_action_item(__('อัปเดตราคาอะไหล่'), function() {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__('กรุณาเลือก Service Type ที่ต้องการอัปเดตราคาอะไหล่'));
				return;
			}

			const names = selected.map(d => d.name);

			frappe.confirm(
				__('ต้องการอัปเดตราคาอะไหล่สำหรับ {0} รายการที่เลือก?', [names.length]),
				function() {
					frappe.call({
						method: 'truck_service_center.truck_service_center.doctype.service_type.service_type.bulk_update_item_prices',
						args: { service_type_names: names },
						freeze: true,
						freeze_message: __('กำลังอัปเดตราคาอะไหล่...'),
						callback: function(r) {
							if (r.message) {
								let msg = r.message;
								frappe.msgprint({
									title: __('ผลการอัปเดตราคาอะไหล่'),
									indicator: msg.failed > 0 ? 'orange' : 'green',
									message: __('อัปเดตสำเร็จ: {0} รายการ<br>ไม่สำเร็จ: {1} รายการ<br>อะไหล่ที่อัปเดตราคา: {2} รายการ',
										[msg.success, msg.failed, msg.items_updated])
								});
								listview.refresh();
							}
						}
					});
				}
			);
		});
	}
};

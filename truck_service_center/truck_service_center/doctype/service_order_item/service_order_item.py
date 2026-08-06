# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ServiceOrderItem(Document):
	# อย่าใส่ validate() ที่นี่ — Frappe ไม่เรียก validate ของ child doctype controller
	# การกันลบ/แก้แถวที่ใบเบิกถูก submit แล้วอยู่ใน ServiceOrder.check_material_issue_items()
	pass

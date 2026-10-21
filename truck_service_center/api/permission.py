import frappe


def has_app_permission():
	"""ใครเห็นแอปนี้ในหน้า Apps / เมนูสลับแอป — ผู้ใช้ desk ที่ไม่ได้ถูกบล็อกโมดูล Truck Service Center"""
	if frappe.session.user == "Administrator":
		return True

	if frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User":
		return False

	# User.get_blocked_modules มีทั้งใน Frappe รุ่นเก่าและรุ่นใหม่
	blocked = frappe.get_cached_doc("User", frappe.session.user).get_blocked_modules()
	return "Truck Service Center" not in blocked

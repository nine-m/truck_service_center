# Copyright (c) 2026, SVL Technology Co. Ltd. and Contributors
# See license.txt

"""ตรรกะจัดกลุ่มของหน้า Bay Monitor — pure function ล้วน ไม่ insert เอกสาร

เคสที่ต้องกันไว้: หน้านี้แสดง "ใช้งานจริง" กับ "การจอง" คู่กัน ถ้าตัดสินว่าใบงานถือช่องไหน
หรือนัดมาถึงหรือยังผิด หน้าจอหน้าศูนย์จะบอกว่าช่องว่างทั้งที่มีรถจอดอยู่
"""

from datetime import datetime, timedelta

import frappe
from frappe.tests import UnitTestCase

from truck_service_center.www.bay_monitor import (
	ARRIVAL_ARRIVED,
	ARRIVAL_LATE,
	ARRIVAL_PENDING,
	STATE_BOOKED,
	STATE_CLOSED,
	STATE_FREE,
	STATE_IN_USE,
	STATE_WAITING,
	appointment_arrival,
	bay_state,
	collect_bookings,
	collect_occupants,
)

NOW = datetime(2026, 10, 28, 10, 0)


def _order(name, status="In Progress", service_bay=None, received=True):
	return frappe._dict(
		name=name,
		status=status,
		service_bay=service_bay,
		received_date=NOW - timedelta(hours=2) if received else None,
		vehicle=f"V-{name}",
		appointment=None,
	)


def _row(parent, service_bay=None, start=None, end=None, service_type="ST"):
	return frappe._dict(
		parent=parent, service_bay=service_bay, start_time=start, end_time=end, service_type=service_type
	)


class UnitTestCollectOccupants(UnitTestCase):
	def test_main_bay_and_unfinished_row_bay_are_held(self):
		occupants, unassigned = collect_occupants(
			[_order("SO-1", service_bay="BAY-01")],
			[_row("SO-1", "BAY-02", start=NOW), _row("SO-1", None)],
			NOW,
		)
		self.assertEqual(set(occupants), {"BAY-01", "BAY-02"})
		self.assertEqual(unassigned, [])
		self.assertEqual(occupants["BAY-02"][0].active_services, ["ST"])
		# แถวที่ช่องจอดว่างใช้ช่องหลัก
		self.assertEqual(occupants["BAY-01"][0].service_count, 1)

	def test_finished_row_releases_its_bay_but_not_the_main_bay(self):
		occupants, _unassigned = collect_occupants(
			[_order("SO-1", service_bay="BAY-01")],
			[_row("SO-1", "BAY-02", start=NOW, end=NOW), _row("SO-1", "BAY-01", start=NOW, end=NOW)],
			NOW,
		)
		self.assertEqual(set(occupants), {"BAY-01"})
		self.assertEqual(occupants["BAY-01"][0].done_count, 1)

	def test_order_without_any_bay_is_unassigned(self):
		occupants, unassigned = collect_occupants([_order("SO-1")], [_row("SO-1")], NOW)
		self.assertEqual(occupants, {})
		self.assertEqual([item.name for item in unassigned], ["SO-1"])
		self.assertTrue(unassigned[0].is_walk_in)

	def test_draft_without_receive_stamp_is_not_in_bay(self):
		occupants, _unassigned = collect_occupants(
			[_order("SO-1", status="Draft", service_bay="BAY-01", received=False)], [], NOW
		)
		self.assertFalse(occupants["BAY-01"][0].in_bay)


class UnitTestAppointmentArrival(UnitTestCase):
	def test_linked_service_order_means_arrived(self):
		appt = frappe._dict(service_order="SO-1", status="Confirmed", appointment_time=timedelta(hours=9))
		self.assertEqual(appointment_arrival(appt, NOW, True), ARRIVAL_ARRIVED)

	def test_past_time_today_is_late_only_today(self):
		appt = frappe._dict(service_order=None, status="Scheduled", appointment_time=timedelta(hours=9))
		self.assertEqual(appointment_arrival(appt, NOW, True), ARRIVAL_LATE)
		self.assertEqual(appointment_arrival(appt, NOW, False), ARRIVAL_PENDING)

	def test_future_time_and_blank_time_are_pending(self):
		later = frappe._dict(service_order=None, status="Scheduled", appointment_time=timedelta(hours=13))
		blank = frappe._dict(service_order=None, status="Scheduled", appointment_time=None)
		self.assertEqual(appointment_arrival(later, NOW, True), ARRIVAL_PENDING)
		self.assertEqual(appointment_arrival(blank, NOW, True), ARRIVAL_PENDING)


class UnitTestCollectBookings(UnitTestCase):
	def test_split_appointment_shows_in_every_bay_and_unallocated_is_separate(self):
		appointments = [
			frappe._dict(name="APT-1", appointment_time=timedelta(hours=8), estimated_duration=6),
			frappe._dict(name="APT-2", appointment_time=timedelta(hours=11), estimated_duration=2),
		]
		bay_rows = [
			frappe._dict(parent="APT-1", service_bay="BAY-01", allocated_hours=4),
			frappe._dict(parent="APT-1", service_bay="PIT-01", allocated_hours=2),
		]
		bookings, unallocated = collect_bookings(appointments, bay_rows, NOW, False)

		self.assertEqual(bookings["BAY-01"][0].allocated_hours, 4)
		self.assertEqual(bookings["PIT-01"][0].allocated_hours, 2)
		self.assertEqual([appt.name for appt in unallocated], ["APT-2"])
		self.assertEqual(bookings["BAY-01"][0].time_label, "08:00")


class UnitTestBayState(UnitTestCase):
	def test_priority(self):
		in_bay = frappe._dict(in_bay=True)
		not_in = frappe._dict(in_bay=False)
		closed = {"is_closed": True}
		open_ = {"is_closed": False}

		# รถจอดจริงชนะแม้วันนั้นปิด
		self.assertEqual(bay_state(closed, [in_bay], [], True), STATE_IN_USE)
		self.assertEqual(bay_state(open_, [not_in], [1], True), STATE_WAITING)
		self.assertEqual(bay_state(closed, [], [1], True), STATE_CLOSED)
		self.assertEqual(bay_state(open_, [], [1], True), STATE_BOOKED)
		self.assertEqual(bay_state(open_, [], [], True), STATE_FREE)
		# วันอื่นไม่ดูรถที่จอดอยู่
		self.assertEqual(bay_state(open_, [in_bay], [], False), STATE_FREE)

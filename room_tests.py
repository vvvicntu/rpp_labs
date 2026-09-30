import unittest
from datetime import datetime, time

from room import (
    BookingId,
    BookingService,
    Capacity,
    DateTimeInterval,
    DomainInvariantViolationError,
    EmployeeId,
    InMemoryRoomRepository,
    InvalidValueObjectError,
    OfficeHours,
    ParticipantCount,
    Room,
    RoomId,
)


class TestRoomBookingDomain(unittest.TestCase):

    def setUp(self):
        self.office_hours = OfficeHours(open_time=time(9, 0), close_time=time(18, 0))
        self.room_id = RoomId.new()
        self.room = Room(room_id=self.room_id, capacity=Capacity(10), office_hours=self.office_hours)
        self.repo = InMemoryRoomRepository()
        self.repo.save(self.room)
        self.service = BookingService()
        self.today = datetime(2026, 9, 28).date()

    # тесты value objects
    def test_invalid_capacity(self):
        with self.assertRaises(InvalidValueObjectError):
            Capacity(0)

    def test_invalid_date_time_interval(self):
        start = datetime.combine(self.today, time(12, 0))
        end = datetime.combine(self.today, time(11, 0))
        with self.assertRaises(InvalidValueObjectError):
            DateTimeInterval(start, end)

    # тесты инвариантов
    def test_exceed_capacity_raises_error(self):
        # 1: участников больше вместимости
        interval = DateTimeInterval(
            datetime.combine(self.today, time(10, 0)),
            datetime.combine(self.today, time(11, 0)),
        )
        with self.assertRaises(DomainInvariantViolationError):
            self.room.add_booking(
                booking_id=BookingId.new(),
                employee_id=EmployeeId.new(),
                interval=interval,
                participants=ParticipantCount(15),
            )

    def test_out_of_office_hours_raises_error(self):
        # 2: выход за рабочие часы
        interval = DateTimeInterval(
            datetime.combine(self.today, time(8, 0)),  # Раньше 9:00
            datetime.combine(self.today, time(10, 0)),
        )
        with self.assertRaises(DomainInvariantViolationError):
            self.room.add_booking(
                booking_id=BookingId.new(),
                employee_id=EmployeeId.new(),
                interval=interval,
                participants=ParticipantCount(5),
            )

    def test_overlapping_booking_raises_error(self):
        # 3: пересечение броней
        interval1 = DateTimeInterval(
            datetime.combine(self.today, time(10, 0)),
            datetime.combine(self.today, time(12, 0)),
        )
        interval2 = DateTimeInterval(
            datetime.combine(self.today, time(11, 0)),  # накладывается на 10:00-12:00
            datetime.combine(self.today, time(13, 0)),
        )
        self.room.add_booking(
            booking_id=BookingId.new(),
            employee_id=EmployeeId.new(),
            interval=interval1,
            participants=ParticipantCount(5),
        )

        with self.assertRaises(DomainInvariantViolationError):
            self.room.add_booking(
                booking_id=BookingId.new(),
                employee_id=EmployeeId.new(),
                interval=interval2,
                participants=ParticipantCount(5),
            )

    # тест доменного сервиса
    def test_successful_booking_via_service(self):
        interval = DateTimeInterval(
            datetime.combine(self.today, time(14, 0)),
            datetime.combine(self.today, time(15, 0)),
        )
        booking_id = BookingId.new()
        employee_id = EmployeeId.new()

        fetched_room = self.repo.get(self.room_id)
        booking = self.service.book_room(
            room=fetched_room,
            employee_id=employee_id,
            booking_id=booking_id,
            interval=interval,
            participants=ParticipantCount(4),
        )
        self.repo.save(fetched_room)

        saved_room = self.repo.get(self.room_id)
        self.assertEqual(len(saved_room.bookings), 1)
        self.assertEqual(saved_room.bookings[0].id, booking.id)


if __name__ == "__main__":
    unittest.main()
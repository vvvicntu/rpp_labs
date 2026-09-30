from dataclasses import dataclass
from datetime import datetime, time
from typing import Protocol
from uuid import UUID, uuid4

# 1. иерархия доменных исключений
class DomainError(Exception):
    # дефолтное исключение домена
    pass

class InvalidValueObjectError(DomainError):
    # ошибка валидации объекта-значения
    pass

class DomainInvariantViolationError(DomainError):
    # нарушение инварианта агрегата
    pass


# 2. объекты-значения 
@dataclass(frozen=True)
class RoomId:
    value: UUID

    @staticmethod
    def new() -> "RoomId":
        return RoomId(uuid4())


@dataclass(frozen=True)
class EmployeeId:
    value: UUID

    @staticmethod
    def new() -> "EmployeeId":
        return EmployeeId(uuid4())


@dataclass(frozen=True)
class BookingId:
    value: UUID

    @staticmethod
    def new() -> "BookingId":
        return BookingId(uuid4())


@dataclass(frozen=True)
class Capacity:
    value: int

    def __post_init__(self):
        if self.value <= 0:
            raise InvalidValueObjectError("Вместимость должна быть больше 0")


@dataclass(frozen=True)
class ParticipantCount:
    value: int

    def __post_init__(self):
        if self.value <= 0:
            raise InvalidValueObjectError("Количество участников должно быть больше 0")


@dataclass(frozen=True)
class OfficeHours:
    open_time: time
    close_time: time

    def __post_init__(self):
        if self.close_time <= self.open_time:
            raise InvalidValueObjectError("Время закрытия должно быть позже времени открытия")

    def contains_interval(self, start_dt: datetime, end_dt: datetime) -> bool:
        return start_dt.time() >= self.open_time and end_dt.time() <= self.close_time


@dataclass(frozen=True)
class DateTimeInterval:
    start_time: datetime
    end_time: datetime

    def __post_init__(self):
        if self.end_time <= self.start_time:
            raise InvalidValueObjectError("Время окончания должно быть позже времени начала")

    def overlaps_with(self, other: "DateTimeInterval") -> bool:
        return max(self.start_time, other.start_time) < min(self.end_time, other.end_time)


# 3. внутренние сущности и агрегаты
class Booking:
    # внутренняя сущность агрегата Room
    def __init__(
        self,
        booking_id: BookingId,
        employee_id: EmployeeId,
        interval: DateTimeInterval,
        participants: ParticipantCount
    ):
        self.id = booking_id
        self.employee_id = employee_id  # связь с другим агрегатом только по ID
        self.interval = interval
        self.participants = participants


class Room:
    # агрегат 1: переговорная комната
    def __init__(self, room_id: RoomId, capacity: Capacity, office_hours: OfficeHours):
        self.id = room_id
        self.capacity = capacity
        self.office_hours = office_hours
        self._bookings: list[Booking] = []

    @property
    def bookings(self) -> list[Booking]:
        return list(self._bookings)

    def add_booking(
        self,
        booking_id: BookingId,
        employee_id: EmployeeId,
        interval: DateTimeInterval,
        participants: ParticipantCount
    ) -> Booking:
        # метод, проверяющий основные инварианты
        # инвариант 1: участники не превышают вместимость
        if participants.value > self.capacity.value:
            raise DomainInvariantViolationError(
                f"Число участников ({participants.value}) превышает вместимость ({self.capacity.value})"
            )

        # инвариант 2: бронь в пределах часов работы офиса
        if not self.office_hours.contains_interval(interval.start_time, interval.end_time):
            raise DomainInvariantViolationError("Бронь выходит за пределы часов работы офиса")

        # инвариант 3: брони на одну комнату не пересекаются
        for existing in self._bookings:
            if existing.interval.overlaps_with(interval):
                raise DomainInvariantViolationError("Бронь пересекается по времени с уже существующей")

        booking = Booking(
            booking_id=booking_id,
            employee_id=employee_id,
            interval=interval,
            participants=participants
        )
        self._bookings.append(booking)
        return booking


class Employee:
    # агрегат 2: сотрудник
    def __init__(self, employee_id: EmployeeId, name: str):
        self.id = employee_id
        self.name = name


# 4. интерфейсы репозиториев 
class RoomRepository(Protocol):
    def get(self, room_id: RoomId) -> Room: ...
    def save(self, room: Room) -> None: ...


# 5. доменный сервис
class BookingService:
    # для операции бронирования
    def book_room(
        self,
        room: Room,
        employee_id: EmployeeId,
        booking_id: BookingId,
        interval: DateTimeInterval,
        participants: ParticipantCount
    ) -> Booking:
        return room.add_booking(booking_id, employee_id, interval, participants)


# 6. адаптер
class InMemoryRoomRepository:
    def __init__(self) -> None:
        self._items: dict[RoomId, Room] = {}

    def get(self, room_id: RoomId) -> Room:
        if room_id not in self._items:
            raise DomainError("Переговорная комната не найдена")
        return self._items[room_id]

    def save(self, room: Room) -> None:
        self._items[room.id] = room

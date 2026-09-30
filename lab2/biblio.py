from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional, Protocol
from uuid import UUID, uuid4

# Иерархия доменных исключений
# Дефолтное исключение домена
class DomainError(Exception):
    pass

# Ошибка валидации объекта-значения
class InvalidValueObjectError(DomainError):
    pass

# Нарушение инварианта агрегата
class DomainInvariantViolationError(DomainError):
    pass


# Объекты-значения
# Книга
@dataclass(frozen=True)
class BookCopyId:
    value: UUID
    # Метод для генерации нового ID
    @staticmethod
    def new() -> "BookCopyId":
        return BookCopyId(uuid4())

# Читатель
@dataclass(frozen=True)
class ReaderId:
    value: UUID

    @staticmethod
    def new() -> "ReaderId":
        return ReaderId(uuid4())

# Выдача 
@dataclass(frozen=True)
class LoanId:
    value: UUID

    @staticmethod
    def new() -> "LoanId":
        return LoanId(uuid4())

# Деньги
@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str = "RUB"

    def __post_init__(self):
        if self.amount < 0:
            raise InvalidValueObjectError("Сумма не может быть отрицательной")
        if self.currency != "RUB":
            raise InvalidValueObjectError("Поддерживается только валюта RUB")

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise InvalidValueObjectError("Нельзя складывать разные валюты")
        return Money(self.amount + other.amount, self.currency)

# Период времени
@dataclass(frozen=True)
class Period:
    start: date
    end: date

    def __post_init__(self):
        if self.start > self.end:
            raise InvalidValueObjectError("Дата начала не может быть позже даты окончания")

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


# Статусы 
class CopyStatus(Enum):
    FREE = "Свободен"
    ISSUED = "Выдан"
    RESTORATION = "На реставрации"

# Внутренняя сущность агрегата loan
@dataclass
class Fine:
    loan_id: LoanId
    reader_id: ReaderId
    amount: Money


# Агрегаты
# Копия книги
class BookCopy:
    def __init__(self, copy_id: BookCopyId, book_id: int):
        self.id = copy_id
        self.book_id = book_id
        self.status = CopyStatus.FREE

    # Инвариант 1. Выдать можно только свободный экземпляр
    def issue(self) -> None:
        if self.status is not CopyStatus.FREE:
            raise DomainInvariantViolationError(f"Нельзя выдать экземпляр в статусе '{self.status.value}'")
        self.status = CopyStatus.ISSUED

    # Инвариант 2. Вернуть можно только выданный экземпляр
    def make_free(self) -> None:
        if self.status is not CopyStatus.ISSUED:
            raise DomainInvariantViolationError("Вернуть можно только экземпляр в статусе 'Выдан'")
        self.status = CopyStatus.FREE


# Выдача книги
class Loan:
    def __init__(self, loan_id: LoanId, copy_id: BookCopyId, reader_id: ReaderId, period: Period):
        self.id = loan_id
        self.copy_id = copy_id      # Связь с другим агрегатом только по ID
        self.reader_id = reader_id  
        self.period = period
        self.actual_end_date: Optional[date] = None
        self.fine: Optional[Fine] = None

    # Инвариант 3. Закрытие выдачи и расчет штрафа при просрочке
    def close_loan(self, return_date: date, daily_fine_rate: Money = Money(Decimal("50.0"))) -> None:
        if self.actual_end_date is not None:
            raise DomainInvariantViolationError("Выдачу нельзя закрыть повторно")

        if return_date < self.period.start:
            raise DomainInvariantViolationError("Дата возврата не может быть раньше даты выдачи")

        self.actual_end_date = return_date

        if return_date > self.period.end:
            overdue_days = (return_date - self.period.end).days
            fine_amount = Money(Decimal(overdue_days) * daily_fine_rate.amount)
            self.fine = Fine(
                loan_id=self.id,
                reader_id=self.reader_id,
                amount=fine_amount
            )


# Порты
class BookCopyRepository(Protocol):
    def get(self, copy_id: BookCopyId) -> BookCopy: ...
    def save(self, copy: BookCopy) -> None: ...


class LoanRepository(Protocol):
    def get(self, loan_id: LoanId) -> Loan: ...
    def save(self, loan: Loan) -> None: ...


# Доменный сервис (координирует выдачу книги между двумя агрегатами)
class IssueBookService:
    def issue_book(self, copy: BookCopy, reader_id: ReaderId, loan_id: LoanId, period: Period) -> Loan:
        copy.issue()
        return Loan(
            loan_id=loan_id,
            copy_id=copy.id,
            reader_id=reader_id,
            period=period
        )


# Реализация репозиториев в памяти (для тестирования)
class InMemoryBookCopyRepository:
    def __init__(self) -> None:
        self._items: dict[BookCopyId, BookCopy] = {}

    def get(self, copy_id: BookCopyId) -> BookCopy:
        if copy_id not in self._items:
            raise DomainError("Экземпляр книги не найден")
        return self._items[copy_id]

    def save(self, copy: BookCopy) -> None:
        self._items[copy.id] = copy


class InMemoryLoanRepository:
    def __init__(self) -> None:
        self._items: dict[LoanId, Loan] = {}

    def get(self, loan_id: LoanId) -> Loan:
        if loan_id not in self._items:
            raise DomainError("Запись о выдаче не найдена")
        return self._items[loan_id]

    def save(self, loan: Loan) -> None:
        self._items[loan.id] = loan


if __name__ == "__main__":
    copy_repo = InMemoryBookCopyRepository()
    loan_repo = InMemoryLoanRepository()
    issue_service = IssueBookService()

    # Создание книги
    copy_id = BookCopyId.new()
    book_copy = BookCopy(copy_id=copy_id, book_id=101)
    copy_repo.save(book_copy)

    # Выдача книги
    loan_id = LoanId.new()
    reader_id = ReaderId.new()
    loan_period = Period(start=date(2026, 9, 1), end=date(2026, 9, 10))

    copy = copy_repo.get(copy_id)
    loan = issue_service.issue_book(copy, reader_id, loan_id, loan_period)

    copy_repo.save(copy)
    loan_repo.save(loan)

    print(f"Книга успешно выдана. Статус: {copy.status.value}")

    # Закрытие с просрочкой
    loan.close_loan(return_date=date(2026, 9, 15))
    copy.make_free()

    copy_repo.save(copy)
    loan_repo.save(loan)

    print(f"Книга возвращена. Новый статус: {copy.status.value}")
    if loan.fine:
        print(f"Начислен штраф: {loan.fine.amount.amount} {loan.fine.amount.currency}")

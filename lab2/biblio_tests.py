import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from biblio import (
    BookCopy,
    BookCopyId,
    CopyStatus,
    DomainError,
    DomainInvariantViolationError,
    InMemoryBookCopyRepository,
    InMemoryLoanRepository,
    InvalidValueObjectError,
    IssueBookService,
    Loan,
    LoanId,
    Money,
    Period,
    ReaderId,
)


class TestValueObjects(unittest.TestCase):
    # 1. тестирование объектов-значений

    def test_money_valid_and_invalid(self):
        m = Money(Decimal("100.0"))
        self.assertEqual(m.amount, Decimal("100.0"))

        with self.assertRaises(InvalidValueObjectError):
            Money(Decimal("-10.0"))

    def test_period_invalid(self):
        with self.assertRaises(InvalidValueObjectError):
            Period(start=date(2026, 9, 10), end=date(2026, 9, 1))


class TestBookCopyAggregate(unittest.TestCase):
    # 2. тестирование агрегата BookCopy

    def test_issue_success(self):
        copy = BookCopy(copy_id=BookCopyId.new(), book_id=101)
        copy.issue()
        self.assertEqual(copy.status, CopyStatus.ISSUED)

    def test_issue_already_issued_fails(self):
        copy = BookCopy(copy_id=BookCopyId.new(), book_id=101)
        copy.issue()
        with self.assertRaises(DomainInvariantViolationError):
            copy.issue()

    def test_make_free_success(self):
        copy = BookCopy(copy_id=BookCopyId.new(), book_id=101)
        copy.issue()
        copy.make_free()
        self.assertEqual(copy.status, CopyStatus.FREE)


class TestLoanAggregate(unittest.TestCase):
    # 3. тестирование агрегата Loan

    def setUp(self):
        self.period = Period(start=date(2026, 9, 1), end=date(2026, 9, 10))

    def test_close_loan_with_fine(self):
        # проверка закрытия выдачи с просрочкой и начисления штрафа
        loan = Loan(
            loan_id=LoanId.new(),
            copy_id=BookCopyId.new(),
            reader_id=ReaderId.new(),
            period=self.period,
        )

        return_date = date(2026, 9, 13)  # просрочка на 3 дня
        loan.close_loan(return_date=return_date, daily_fine_rate=Money(Decimal("50.0")))

        self.assertEqual(loan.actual_end_date, return_date)
        self.assertIsNotNone(loan.fine)
        self.assertEqual(loan.fine.amount.amount, Decimal("150.0"))  # 3 дня * 50 руб

    def test_close_loan_twice_fails(self):
        # инвариант: нельзя закрыть выдачу повторно
        loan = Loan(
            loan_id=LoanId.new(),
            copy_id=BookCopyId.new(),
            reader_id=ReaderId.new(),
            period=self.period,
        )
        loan.close_loan(return_date=date(2026, 9, 10))

        with self.assertRaises(DomainInvariantViolationError):
            loan.close_loan(return_date=date(2026, 9, 10))


class TestIssueBookService(unittest.TestCase):
    # 4. тестирование доменного сервиса

    def setUp(self):
        self.copy_repo = InMemoryBookCopyRepository()
        self.loan_repo = InMemoryLoanRepository()
        self.service = IssueBookService()

    def test_issue_book_success(self):
        copy_id = BookCopyId.new()
        copy = BookCopy(copy_id=copy_id, book_id=101)
        self.copy_repo.save(copy)

        loan_id = LoanId.new()
        reader_id = ReaderId.new()
        period = Period(start=date(2026, 9, 1), end=date(2026, 9, 10))

        fetched_copy = self.copy_repo.get(copy_id)
        loan = self.service.issue_book(fetched_copy, reader_id, loan_id, period)
        self.copy_repo.save(fetched_copy)
        self.loan_repo.save(loan)

        saved_copy = self.copy_repo.get(copy_id)
        self.assertEqual(saved_copy.status, CopyStatus.ISSUED)
        self.assertEqual(loan.copy_id, copy_id)

    def test_repository_not_found(self):
        with self.assertRaises(DomainError):
            self.copy_repo.get(BookCopyId.new())


if __name__ == "__main__":
    unittest.main()

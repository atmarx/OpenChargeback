"""Tests for database repository operations."""

import pytest

from focus_billing.db.repository import (
    Database,
    BillingPeriod,
    Source,
    Charge,
    Statement,
    Import,
    EmailLog,
)


class TestDatabaseInitialization:
    """Tests for database initialization."""

    def test_initialize_creates_tables(self, temp_db):
        """Initialize creates schema tables."""
        from sqlalchemy import inspect

        db = Database(temp_db)
        db.initialize()

        # Verify tables exist using SQLAlchemy inspect
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())

        assert "billing_periods" in tables
        assert "sources" in tables
        assert "charges" in tables
        assert "statements" in tables
        assert "imports" in tables

    def test_initialize_idempotent(self, temp_db):
        """Initialize can be called multiple times."""
        db = Database(temp_db)
        db.initialize()
        db.initialize()  # Should not raise

    def test_engine_lazy(self, temp_db):
        """Engine is created lazily."""
        db = Database(temp_db)
        assert db._engine is None

        # Access engine
        _ = db.engine
        assert db._engine is not None

    def test_close_disposes_engine(self, temp_db):
        """Close disposes the engine."""
        db = Database(temp_db)
        db.initialize()
        db.close()
        assert db._engine is None


class TestBillingPeriodOperations:
    """Tests for billing period operations."""

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized database."""
        database = Database(temp_db)
        database.initialize()
        return database

    def test_get_or_create_period_new(self, db):
        """Create new period when doesn't exist."""
        period = db.get_or_create_period("2025-01")

        assert period.id is not None
        assert period.period == "2025-01"
        assert period.status == "open"
        assert period.opened_at is not None

    def test_get_or_create_period_existing(self, db):
        """Return existing period when exists."""
        period1 = db.get_or_create_period("2025-01")
        period2 = db.get_or_create_period("2025-01")

        assert period1.id == period2.id

    def test_get_period_existing(self, db):
        """Get existing period by period string."""
        db.get_or_create_period("2025-02")
        period = db.get_period("2025-02")

        assert period is not None
        assert period.period == "2025-02"

    def test_get_period_nonexistent(self, db):
        """Get nonexistent period returns None."""
        period = db.get_period("2099-12")
        assert period is None

    def test_get_period_by_id(self, db):
        """Get period by ID."""
        created = db.get_or_create_period("2025-03")
        period = db.get_period_by_id(created.id)

        assert period is not None
        assert period.period == "2025-03"

    def test_list_periods_empty(self, db):
        """List periods when none exist."""
        periods = db.list_periods()
        assert periods == []

    def test_list_periods_multiple(self, db):
        """List multiple periods in descending order."""
        db.get_or_create_period("2025-01")
        db.get_or_create_period("2025-03")
        db.get_or_create_period("2025-02")

        periods = db.list_periods()

        assert len(periods) == 3
        assert periods[0].period == "2025-03"
        assert periods[1].period == "2025-02"
        assert periods[2].period == "2025-01"

    def test_update_period_status_closed(self, db):
        """Close a period."""
        db.get_or_create_period("2025-01")
        period = db.update_period_status("2025-01", "closed")

        assert period.status == "closed"
        assert period.closed_at is not None

    def test_update_period_status_finalized(self, db):
        """Finalize a period."""
        db.get_or_create_period("2025-01")
        period = db.update_period_status("2025-01", "finalized")

        assert period.status == "finalized"
        assert period.finalized_at is not None

    def test_update_period_with_notes(self, db):
        """Update period with notes."""
        db.get_or_create_period("2025-01")
        period = db.update_period_status(
            "2025-01", "closed", notes="Closed for review"
        )

        assert period.notes == "Closed for review"

    def test_reopen_closed_period(self, db):
        """Reopen a closed period."""
        period = db.get_or_create_period("2025-01")
        db.update_period_status("2025-01", "closed")

        reopened = db.reopen_period(period.id, "Need more imports")

        assert reopened is not None
        assert reopened.status == "open"
        assert reopened.reopen_reason == "Need more imports"

    def test_reopen_finalized_period_fails(self, db):
        """Cannot reopen a finalized period - finalization is permanent."""
        period = db.get_or_create_period("2025-01")
        db.update_period_status("2025-01", "finalized")

        result = db.reopen_period(period.id, "Trying to reopen")

        assert result is None
        # Verify period is still finalized
        period = db.get_period_by_id(period.id)
        assert period.status == "finalized"


class TestSourceOperations:
    """Tests for source operations."""

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized database."""
        database = Database(temp_db)
        database.initialize()
        return database

    def test_get_or_create_source_new(self, db):
        """Create new source when doesn't exist."""
        source = db.get_or_create_source("aws", "api")

        assert source.id is not None
        assert source.name == "aws"
        assert source.source_type == "api"
        assert source.enabled is True

    def test_get_or_create_source_existing(self, db):
        """Return existing source when exists."""
        source1 = db.get_or_create_source("aws", "api")
        source2 = db.get_or_create_source("aws", "api")

        assert source1.id == source2.id

    def test_get_or_create_source_display_name(self, db):
        """Source with custom display name."""
        source = db.get_or_create_source(
            "aws",
            "api",
            display_name="Amazon Web Services"
        )

        assert source.display_name == "Amazon Web Services"

    def test_get_source_existing(self, db):
        """Get existing source by name."""
        db.get_or_create_source("azure", "file")
        source = db.get_source("azure")

        assert source is not None
        assert source.name == "azure"

    def test_get_source_nonexistent(self, db):
        """Get nonexistent source returns None."""
        source = db.get_source("nonexistent")
        assert source is None

    def test_list_sources_empty(self, db):
        """List sources when none exist."""
        sources = db.list_sources()
        assert sources == []

    def test_list_sources_multiple(self, db):
        """List multiple sources."""
        db.get_or_create_source("aws", "api")
        db.get_or_create_source("azure", "file")
        db.get_or_create_source("gcp", "api")

        sources = db.list_sources()

        assert len(sources) == 3
        names = {s.name for s in sources}
        assert names == {"aws", "azure", "gcp"}

    def test_update_source_sync_success(self, db):
        """Update source sync status to success."""
        db.get_or_create_source("aws", "api")
        db.update_source_sync("aws", "success")

        source = db.get_source("aws")
        assert source.last_sync_status == "success"
        assert source.last_sync_at is not None

    def test_update_source_sync_error(self, db):
        """Update source sync status with error message."""
        db.get_or_create_source("aws", "api")
        db.update_source_sync("aws", "error", "Connection failed")

        source = db.get_source("aws")
        assert source.last_sync_status == "error"
        assert source.last_sync_message == "Connection failed"


class TestChargeOperations:
    """Tests for charge operations."""

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized database."""
        database = Database(temp_db)
        database.initialize()
        return database

    @pytest.fixture
    def period(self, db):
        """Create a billing period."""
        return db.get_or_create_period("2025-01")

    @pytest.fixture
    def source(self, db):
        """Create a source."""
        return db.get_or_create_source("test-source", "file")

    def test_insert_single_charge(self, db, period, source):
        """Insert a single charge."""
        charge = Charge(
            id=None,
            billing_period_id=period.id,
            source_id=source.id,
            charge_period_start="2025-01-01",
            charge_period_end="2025-01-02",
            list_cost=None,
            contracted_cost=None,
            billed_cost=100.50,
            effective_cost=100.50,
            resource_id="res-123",
            resource_name="web-server",
            service_name="Amazon EC2",
            pi_email="researcher@example.edu",
            project_id="genomics-1",
            fund_org="12345",
            raw_tags={"custom": "value"},
            needs_review=False,
        )

        counts = db.insert_charges([charge])
        assert counts["inserted"] == 1

        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 1
        assert charges[0].billed_cost == pytest.approx(100.50)

    def test_insert_multiple_charges(self, db, period, source):
        """Insert multiple charges."""
        charges = [
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start=f"2025-01-0{i}",
                charge_period_end=f"2025-01-0{i+1}",
                list_cost=None,
                contracted_cost=None,
                billed_cost=10.0 * i,
                effective_cost=None,
                resource_id=f"res-{i}",
                resource_name=f"server-{i}",
                service_name="Amazon EC2",
                pi_email="test@example.edu",
                project_id="project-1",
                fund_org="12345",
                raw_tags=None,
            )
            for i in range(1, 6)
        ]

        counts = db.insert_charges(charges)
        assert counts["inserted"] == 5

    def test_upsert_updates_existing(self, db, period, source):
        """Upsert updates existing charge with same key."""
        charge1 = Charge(
            id=None,
            billing_period_id=period.id,
            source_id=source.id,
            charge_period_start="2025-01-01",
            charge_period_end="2025-01-02",
            list_cost=None,
            contracted_cost=None,
            billed_cost=100.00,
            effective_cost=None,
            resource_id="res-123",
            resource_name="server",
            service_name="EC2",
            pi_email="test@example.edu",
            project_id="project-1",
            fund_org="12345",
            raw_tags=None,
        )
        db.insert_charges([charge1])

        # Insert same charge with updated cost
        charge2 = Charge(
            id=None,
            billing_period_id=period.id,
            source_id=source.id,
            charge_period_start="2025-01-01",
            charge_period_end="2025-01-02",
            list_cost=None,
            contracted_cost=None,
            billed_cost=200.00,  # Updated
            effective_cost=None,
            resource_id="res-123",  # Same resource
            resource_name="server-updated",
            service_name="EC2",
            pi_email="test@example.edu",
            project_id="project-1",
            fund_org="12345",
            raw_tags=None,
        )
        db.insert_charges([charge2])

        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 1
        assert charges[0].billed_cost == pytest.approx(200.00)

    def test_get_charges_excludes_flagged(self, db, period, source):
        """Get charges without flagged ones."""
        charges = [
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start="2025-01-01",
                charge_period_end="2025-01-02",
                list_cost=None,
                contracted_cost=None,
                billed_cost=100.00,
                effective_cost=None,
                resource_id="res-1",
                resource_name="server-1",
                service_name="EC2",
                pi_email="test@example.edu",
                project_id="project-1",
                fund_org="12345",
                raw_tags=None,
                needs_review=False,
            ),
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start="2025-01-02",
                charge_period_end="2025-01-03",
                list_cost=None,
                contracted_cost=None,
                billed_cost=50.00,
                effective_cost=None,
                resource_id="res-2",
                resource_name="server-2",
                service_name="EC2",
                pi_email="test@example.edu",
                project_id="project-1",
                fund_org="12345",
                raw_tags=None,
                needs_review=True,
                review_reason="missing_project",
            ),
        ]
        db.insert_charges(charges)

        # Without flagged
        charges_no_flagged = db.get_charges_for_period(
            period.id, include_flagged=False
        )
        assert len(charges_no_flagged) == 1

        # With flagged
        charges_all = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges_all) == 2

    def test_get_flagged_charges(self, db, period, source):
        """Get only flagged charges."""
        charges = [
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start="2025-01-01",
                charge_period_end="2025-01-02",
                list_cost=None,
                contracted_cost=None,
                billed_cost=100.00,
                effective_cost=None,
                resource_id="res-1",
                resource_name="server-1",
                service_name="EC2",
                pi_email="test@example.edu",
                project_id="project-1",
                fund_org="12345",
                raw_tags=None,
                needs_review=False,
            ),
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start="2025-01-02",
                charge_period_end="2025-01-03",
                list_cost=None,
                contracted_cost=None,
                billed_cost=50.00,
                effective_cost=None,
                resource_id="res-2",
                resource_name="server-2",
                service_name="EC2",
                pi_email="test@example.edu",
                project_id=None,
                fund_org="12345",
                raw_tags=None,
                needs_review=True,
                review_reason="missing_project",
            ),
        ]
        db.insert_charges(charges)

        flagged = db.get_flagged_charges(period.id)
        assert len(flagged) == 1
        assert flagged[0].review_reason == "missing_project"

    def test_approve_charge(self, db, period, source):
        """Approve a flagged charge."""
        charge = Charge(
            id=None,
            billing_period_id=period.id,
            source_id=source.id,
            charge_period_start="2025-01-01",
            charge_period_end="2025-01-02",
            list_cost=None,
            contracted_cost=None,
            billed_cost=100.00,
            effective_cost=None,
            resource_id="res-1",
            resource_name="server",
            service_name="EC2",
            pi_email="test@example.edu",
            project_id=None,
            fund_org="12345",
            raw_tags=None,
            needs_review=True,
        )
        db.insert_charges([charge])

        flagged = db.get_flagged_charges(period.id)
        assert len(flagged) == 1

        db.approve_charge(flagged[0].id)

        # Should no longer be flagged
        flagged_after = db.get_flagged_charges(period.id)
        assert len(flagged_after) == 0

    def test_approve_all_charges(self, db, period, source):
        """Approve all flagged charges in a period."""
        charges = [
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start=f"2025-01-0{i}",
                charge_period_end=f"2025-01-0{i+1}",
                list_cost=None,
                contracted_cost=None,
                billed_cost=10.00,
                effective_cost=None,
                resource_id=f"res-{i}",
                resource_name=f"server-{i}",
                service_name="EC2",
                pi_email="test@example.edu",
                project_id=None,
                fund_org="12345",
                raw_tags=None,
                needs_review=True,
            )
            for i in range(1, 4)
        ]
        db.insert_charges(charges)

        count = db.approve_all_charges(period.id)
        assert count == 3

        flagged = db.get_flagged_charges(period.id)
        assert len(flagged) == 0

    def test_reject_charge(self, db, period, source):
        """Reject (delete) a charge."""
        charge = Charge(
            id=None,
            billing_period_id=period.id,
            source_id=source.id,
            charge_period_start="2025-01-01",
            charge_period_end="2025-01-02",
            list_cost=None,
            contracted_cost=None,
            billed_cost=100.00,
            effective_cost=None,
            resource_id="res-1",
            resource_name="server",
            service_name="EC2",
            pi_email="test@example.edu",
            project_id=None,
            fund_org="12345",
            raw_tags=None,
            needs_review=True,
        )
        db.insert_charges([charge])

        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 1

        db.reject_charge(charges[0].id)

        charges_after = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges_after) == 0


class TestStatementOperations:
    """Tests for statement operations."""

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized database."""
        database = Database(temp_db)
        database.initialize()
        return database

    @pytest.fixture
    def period(self, db):
        """Create a billing period."""
        return db.get_or_create_period("2025-01")

    def test_upsert_statement_new(self, db, period):
        """Insert new statement."""
        statement = Statement(
            id=None,
            billing_period_id=period.id,
            pi_email="researcher@example.edu",
            total_cost=500.00,
            project_count=3,
            pdf_path="/output/statement.pdf",
        )

        statement_id = db.upsert_statement(statement)
        assert statement_id is not None

    def test_upsert_statement_update(self, db, period):
        """Update existing statement."""
        statement1 = Statement(
            id=None,
            billing_period_id=period.id,
            pi_email="researcher@example.edu",
            total_cost=500.00,
            project_count=3,
            pdf_path="/output/statement.pdf",
        )
        db.upsert_statement(statement1)

        # Update same PI/period
        statement2 = Statement(
            id=None,
            billing_period_id=period.id,
            pi_email="researcher@example.edu",
            total_cost=750.00,
            project_count=4,
            pdf_path="/output/statement-v2.pdf",
        )
        db.upsert_statement(statement2)

        statements = db.get_statements_for_period(period.id)
        assert len(statements) == 1
        assert statements[0].total_cost == pytest.approx(750.00)

    def test_get_statements_for_period(self, db, period):
        """Get all statements for a period."""
        for email in ["pi1@example.edu", "pi2@example.edu", "pi3@example.edu"]:
            statement = Statement(
                id=None,
                billing_period_id=period.id,
                pi_email=email,
                total_cost=100.00,
                project_count=1,
            )
            db.upsert_statement(statement)

        statements = db.get_statements_for_period(period.id)
        assert len(statements) == 3

    def test_mark_statement_sent(self, db, period):
        """Mark statement as sent."""
        statement = Statement(
            id=None,
            billing_period_id=period.id,
            pi_email="researcher@example.edu",
            total_cost=500.00,
            project_count=3,
        )
        statement_id = db.upsert_statement(statement)

        db.mark_statement_sent(statement_id)

        statements = db.get_statements_for_period(period.id)
        assert statements[0].sent_at is not None


class TestImportOperations:
    """Tests for import log operations."""

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized database."""
        database = Database(temp_db)
        database.initialize()
        return database

    @pytest.fixture
    def period(self, db):
        """Create a billing period."""
        return db.get_or_create_period("2025-01")

    @pytest.fixture
    def source(self, db):
        """Create a source."""
        return db.get_or_create_source("test-source", "file")

    def test_log_import(self, db, period, source):
        """Log an import operation."""
        import_record = Import(
            id=None,
            filename="/data/billing.csv",
            source_id=source.id,
            billing_period_id=period.id,
            row_count=100,
            total_cost=5000.00,
            flagged_rows=5,
            flagged_cost=250.00,
        )

        import_id = db.log_import(import_record)
        assert import_id is not None

    def test_get_imports_for_period(self, db, period, source):
        """Get import logs for a period."""
        for i in range(3):
            import_record = Import(
                id=None,
                filename=f"/data/billing-{i}.csv",
                source_id=source.id,
                billing_period_id=period.id,
                row_count=100,
                total_cost=1000.00,
            )
            db.log_import(import_record)

        imports = db.get_imports_for_period(period.id)
        assert len(imports) == 3


class TestTransactions:
    """Tests for transaction handling."""

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized database."""
        database = Database(temp_db)
        database.initialize()
        return database

    def test_transaction_commits(self, db):
        """Successful operations commit via engine.begin()."""
        from focus_billing.db.tables import billing_periods

        with db.engine.begin() as conn:
            conn.execute(
                billing_periods.insert().values(period="2025-06")
            )

        # Should persist after context
        period = db.get_period("2025-06")
        assert period is not None

    def test_transaction_rollbacks_on_error(self, db):
        """Errors cause rollback via engine.begin()."""
        from focus_billing.db.tables import billing_periods

        try:
            with db.engine.begin() as conn:
                conn.execute(
                    billing_periods.insert().values(period="2025-07")
                )
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Should not persist
        period = db.get_period("2025-07")
        assert period is None


class TestEmailLogOperations:
    """Tests for email log operations."""

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized database."""
        database = Database(temp_db)
        database.initialize()
        return database

    @pytest.fixture
    def period(self, db):
        """Create a billing period."""
        return db.get_or_create_period("2025-01")

    @pytest.fixture
    def statement(self, db, period):
        """Create a statement."""
        stmt = Statement(
            id=None,
            billing_period_id=period.id,
            pi_email="researcher@example.edu",
            total_cost=500.00,
            project_count=3,
            pdf_path="/output/statement.pdf",
        )
        stmt_id = db.upsert_statement(stmt)
        return db.get_statement_by_id(stmt_id)

    def test_log_email_success(self, db):
        """Log a successful email send."""
        email_id = db.log_email(
            recipient="test@example.edu",
            subject="Test Subject",
            status="success",
            sent_by="admin",
        )
        assert email_id > 0

    def test_log_email_dev_mode(self, db):
        """Log a dev mode email (file output)."""
        email_id = db.log_email(
            recipient="test@example.edu",
            subject="Test Subject",
            status="dev_mode",
            sent_by="admin",
        )

        logs = db.get_email_logs()
        assert len(logs) == 1
        assert logs[0].status == "dev_mode"

    def test_log_email_error(self, db):
        """Log a failed email with error message."""
        email_id = db.log_email(
            recipient="test@example.edu",
            subject="Test Subject",
            status="error",
            sent_by="admin",
            error_message="SMTP connection refused",
        )

        logs = db.get_email_logs()
        assert len(logs) == 1
        assert logs[0].status == "error"
        assert logs[0].error_message == "SMTP connection refused"

    def test_log_email_with_statement(self, db, statement):
        """Log email with associated statement."""
        email_id = db.log_email(
            recipient="researcher@example.edu",
            subject="Billing Statement",
            status="success",
            sent_by="admin",
            statement_id=statement.id,
        )

        logs = db.get_email_logs()
        assert len(logs) == 1
        assert logs[0].statement_id == statement.id

    def test_get_email_logs_empty(self, db):
        """Get email logs when none exist."""
        logs = db.get_email_logs()
        assert logs == []

    def test_get_email_logs_multiple(self, db):
        """Get multiple email logs in descending order."""
        for i in range(5):
            db.log_email(
                recipient=f"user{i}@example.edu",
                subject=f"Subject {i}",
                status="success",
                sent_by="admin",
            )

        logs = db.get_email_logs()
        assert len(logs) == 5

    def test_get_email_logs_filter_by_recipient(self, db):
        """Filter email logs by recipient."""
        for i in range(3):
            db.log_email(
                recipient="user1@example.edu",
                subject=f"Subject {i}",
                status="success",
                sent_by="admin",
            )
        for i in range(2):
            db.log_email(
                recipient="user2@example.edu",
                subject=f"Subject {i}",
                status="success",
                sent_by="admin",
            )

        logs = db.get_email_logs(recipient="user1@example.edu")
        assert len(logs) == 3

    def test_get_email_logs_limit(self, db):
        """Limit email logs returned."""
        for i in range(10):
            db.log_email(
                recipient=f"user{i}@example.edu",
                subject=f"Subject {i}",
                status="success",
                sent_by="admin",
            )

        logs = db.get_email_logs(limit=5)
        assert len(logs) == 5

    def test_clear_email_logs(self, db):
        """Clear all email logs."""
        for i in range(5):
            db.log_email(
                recipient=f"user{i}@example.edu",
                subject=f"Subject {i}",
                status="success",
                sent_by="admin",
            )

        count = db.clear_email_logs()
        assert count == 5

        logs = db.get_email_logs()
        assert len(logs) == 0


class TestStatementByIdOperations:
    """Tests for get_statement_by_id operation."""

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized database."""
        database = Database(temp_db)
        database.initialize()
        return database

    @pytest.fixture
    def period(self, db):
        """Create a billing period."""
        return db.get_or_create_period("2025-01")

    def test_get_statement_by_id_existing(self, db, period):
        """Get existing statement by ID."""
        statement = Statement(
            id=None,
            billing_period_id=period.id,
            pi_email="researcher@example.edu",
            total_cost=500.00,
            project_count=3,
            pdf_path="/output/statement.pdf",
        )
        statement_id = db.upsert_statement(statement)

        result = db.get_statement_by_id(statement_id)

        assert result is not None
        assert result.id == statement_id
        assert result.pi_email == "researcher@example.edu"
        assert result.total_cost == pytest.approx(500.00)
        assert result.pdf_path == "/output/statement.pdf"

    def test_get_statement_by_id_nonexistent(self, db):
        """Get nonexistent statement returns None."""
        result = db.get_statement_by_id(99999)
        assert result is None

    def test_get_statement_by_id_includes_sent_at(self, db, period):
        """Get statement includes sent_at timestamp."""
        statement = Statement(
            id=None,
            billing_period_id=period.id,
            pi_email="researcher@example.edu",
            total_cost=500.00,
            project_count=3,
        )
        statement_id = db.upsert_statement(statement)

        # Initially not sent
        result = db.get_statement_by_id(statement_id)
        assert result.sent_at is None

        # Mark as sent
        db.mark_statement_sent(statement_id)

        # Should now have sent_at
        result = db.get_statement_by_id(statement_id)
        assert result.sent_at is not None


class TestJournalExportOperations:
    """Tests for journal export logging operations."""

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized database."""
        database = Database(temp_db)
        database.initialize()
        return database

    @pytest.fixture
    def period(self, db):
        """Create a billing period."""
        return db.get_or_create_period("2025-01")

    def test_log_journal_export(self, db, period):
        """Log a journal export."""
        export_id = db.log_journal_export(
            billing_period_id=period.id,
            format="standard",
            include_flagged=False,
            row_count=100,
            total_cost=5000.00,
            exported_by="admin",
            filename="journal_2025-01_standard_20250117.csv",
        )

        assert export_id > 0

    def test_get_journal_exports_empty(self, db):
        """Get exports when none exist."""
        exports = db.get_journal_exports()
        assert len(exports) == 0

    def test_get_journal_exports(self, db, period):
        """Get journal exports."""
        db.log_journal_export(
            billing_period_id=period.id,
            format="standard",
            include_flagged=False,
            row_count=100,
            total_cost=5000.00,
            exported_by="admin",
        )

        exports = db.get_journal_exports()

        assert len(exports) == 1
        assert exports[0].format == "standard"
        assert exports[0].row_count == 100
        assert exports[0].total_cost == pytest.approx(5000.00)
        assert exports[0].exported_by == "admin"
        assert exports[0].period == "2025-01"

    def test_get_journal_exports_multiple(self, db, period):
        """Get multiple journal exports."""
        db.log_journal_export(
            billing_period_id=period.id,
            format="standard",
            include_flagged=False,
            row_count=100,
            total_cost=5000.00,
        )
        db.log_journal_export(
            billing_period_id=period.id,
            format="summary",
            include_flagged=True,
            row_count=25,
            total_cost=5000.00,
        )
        db.log_journal_export(
            billing_period_id=period.id,
            format="gl",
            include_flagged=False,
            row_count=10,
            total_cost=5000.00,
        )

        exports = db.get_journal_exports()

        assert len(exports) == 3

    def test_get_journal_exports_limit(self, db, period):
        """Test limit on journal exports."""
        for i in range(5):
            db.log_journal_export(
                billing_period_id=period.id,
                format="standard",
                include_flagged=False,
                row_count=i + 1,
                total_cost=100.00 * (i + 1),
            )

        exports = db.get_journal_exports(limit=3)
        assert len(exports) == 3

    def test_clear_journal_exports(self, db, period):
        """Clear all journal exports."""
        for i in range(5):
            db.log_journal_export(
                billing_period_id=period.id,
                format="standard",
                include_flagged=False,
                row_count=10,
                total_cost=100.00,
            )

        count = db.clear_journal_exports()
        assert count == 5

        exports = db.get_journal_exports()
        assert len(exports) == 0

    def test_journal_export_include_flagged(self, db, period):
        """Test include_flagged flag is stored correctly."""
        db.log_journal_export(
            billing_period_id=period.id,
            format="standard",
            include_flagged=True,
            row_count=50,
            total_cost=2500.00,
        )

        exports = db.get_journal_exports()
        assert len(exports) == 1
        assert exports[0].include_flagged is True

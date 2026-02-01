"""Pydantic schemas for web request/response validation."""

from pydantic import BaseModel


class LoginForm(BaseModel):
    """Login form data."""

    username: str
    password: str


class PeriodStats(BaseModel):
    """Statistics for a billing period."""

    total_charges: float
    charge_count: int
    pi_count: int
    project_count: int
    flagged_count: int
    flagged_cost: float


class DashboardData(BaseModel):
    """Data for the dashboard view."""

    current_period: str | None
    stats: PeriodStats | None
    recent_imports: list[dict]
    top_pis: list[dict]


class ChargeFilters(BaseModel):
    """Filters for charge listing."""

    period_id: int | None = None
    source_id: int | None = None
    pi_email: str | None = None
    search: str | None = None
    needs_review: bool | None = None
    page: int = 1
    per_page: int = 50


class PaginatedResponse(BaseModel):
    """Generic paginated response."""

    items: list
    total: int
    page: int
    per_page: int
    pages: int

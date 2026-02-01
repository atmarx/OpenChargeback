"""PDF statement generation using WeasyPrint."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import Config
from ..processing.aggregator import ProjectSummary

# Default template if no custom template exists
DEFAULT_STATEMENT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Research Computing Statement</title>
    <style>
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            font-size: 8pt;
            line-height: 1.3;
            color: #333;
            margin: 0;
            padding: 20px;
        }
        .header {
            border-bottom: 2px solid #2c3e50;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }
        .header h1 {
            margin: 0;
            color: #2c3e50;
            font-size: 16pt;
        }
        .header .subtitle {
            color: #7f8c8d;
            margin-top: 3px;
            font-size: 9pt;
        }
        .meta-info {
            display: flex;
            justify-content: space-between;
            margin-bottom: 15px;
            background: #f8f9fa;
            padding: 10px;
            border-radius: 5px;
        }
        .meta-info div {
            flex: 1;
        }
        .meta-info label {
            font-weight: bold;
            color: #7f8c8d;
            font-size: 7pt;
            text-transform: uppercase;
        }
        .meta-info .value {
            font-size: 9pt;
            margin-top: 2px;
        }
        h2 {
            color: #2c3e50;
            border-bottom: 1px solid #ecf0f1;
            padding-bottom: 5px;
            font-size: 11pt;
            margin-top: 15px;
            margin-bottom: 10px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 15px;
        }
        th {
            background: #2c3e50;
            color: white;
            padding: 5px;
            text-align: left;
            font-size: 7pt;
        }
        td {
            padding: 4px 5px;
            border-bottom: 1px solid #ecf0f1;
            font-size: 7pt;
        }
        tr:nth-child(even) {
            background: #f8f9fa;
        }
        .amount {
            text-align: right;
            font-family: 'Courier New', monospace;
        }
        .discount {
            text-align: right;
            color: #27ae60;
        }
        .total-row {
            font-weight: bold;
            background: #ecf0f1 !important;
        }
        .total-row td {
            border-top: 2px solid #2c3e50;
        }
        .footer {
            margin-top: 20px;
            padding-top: 10px;
            border-top: 1px solid #ecf0f1;
            font-size: 7pt;
            color: #7f8c8d;
        }
        .summary-box {
            display: flex;
            justify-content: space-between;
            margin-top: 10px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 5px;
        }
        .summary-item {
            text-align: center;
        }
        .summary-item .label {
            font-size: 7pt;
            color: #7f8c8d;
            text-transform: uppercase;
        }
        .summary-item .value {
            font-size: 14pt;
            font-weight: bold;
            margin-top: 3px;
        }
        .summary-item .value.list-price {
            color: #7f8c8d;
            text-decoration: line-through;
        }
        .summary-item .value.discount {
            color: #27ae60;
        }
        .summary-item .value.final {
            color: #2c3e50;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Research Computing Statement</h1>
        <div class="subtitle">{{ organization_name }}</div>
    </div>

    <div class="meta-info">
        <div>
            <label>Billing Period</label>
            <div class="value">{{ period }}</div>
        </div>
        <div>
            <label>Principal Investigator</label>
            <div class="value">{{ pi_email }}</div>
        </div>
        <div>
            <label>Project</label>
            <div class="value">{{ project_id }}</div>
        </div>
        <div>
            <label>Fund/Org</label>
            <div class="value">{{ fund_org or 'N/A' }}</div>
        </div>
    </div>

    {% if total_discount > 0 %}
    <div class="summary-box">
        <div class="summary-item">
            <div class="label">List Price</div>
            <div class="value list-price">${{ "%.2f"|format(total_list_cost) }}</div>
        </div>
        <div class="summary-item">
            <div class="label">Your Discount</div>
            <div class="value discount">-${{ "%.2f"|format(total_discount) }} ({{ "%.0f"|format(discount_percent) }}%)</div>
        </div>
        <div class="summary-item">
            <div class="label">Amount Due</div>
            <div class="value final">${{ "%.2f"|format(total_cost) }}</div>
        </div>
    </div>
    {% endif %}

    <h2>Charges by Service</h2>
    <table>
        <thead>
            <tr>
                <th>Service</th>
                {% if total_discount > 0 %}
                <th class="amount">List Price</th>
                <th class="amount">Discount</th>
                {% endif %}
                <th class="amount">Amount</th>
            </tr>
        </thead>
        <tbody>
            {% for service, amount in service_breakdown.items() %}
            {% set list_amount = service_list_breakdown.get(service, amount) %}
            {% set service_discount = list_amount - amount %}
            <tr>
                <td>{{ service }}</td>
                {% if total_discount > 0 %}
                <td class="amount">${{ "%.2f"|format(list_amount) }}</td>
                <td class="discount">{% if service_discount > 0 %}-${{ "%.2f"|format(service_discount) }}{% else %}-{% endif %}</td>
                {% endif %}
                <td class="amount">${{ "%.2f"|format(amount) }}</td>
            </tr>
            {% endfor %}
            <tr class="total-row">
                <td>Total</td>
                {% if total_discount > 0 %}
                <td class="amount">${{ "%.2f"|format(total_list_cost) }}</td>
                <td class="discount">-${{ "%.2f"|format(total_discount) }}</td>
                {% endif %}
                <td class="amount">${{ "%.2f"|format(total_cost) }}</td>
            </tr>
        </tbody>
    </table>

    <h2>Charge Details</h2>
    <table>
        <thead>
            <tr>
                <th>Date</th>
                <th>Resource</th>
                <th>Service</th>
                {% if total_discount > 0 %}
                <th class="amount">List</th>
                <th class="amount">Discount</th>
                {% endif %}
                <th class="amount">Amount</th>
            </tr>
        </thead>
        <tbody>
            {% for charge in charges %}
            {% set charge_list = charge.list_cost if charge.list_cost else charge.billed_cost %}
            {% set charge_discount = charge_list - charge.billed_cost %}
            <tr>
                <td>{{ charge.charge_period_start or 'N/A' }}</td>
                <td>{{ charge.resource_name or charge.resource_id or 'N/A' }}</td>
                <td>{{ charge.service_name or 'N/A' }}</td>
                {% if total_discount > 0 %}
                <td class="amount">${{ "%.2f"|format(charge_list) }}</td>
                <td class="discount">{% if charge_discount > 0 %}-${{ "%.2f"|format(charge_discount) }}{% else %}-{% endif %}</td>
                {% endif %}
                <td class="amount">${{ "%.2f"|format(charge.billed_cost) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    {% if total_discount > 0 %}
    <div class="summary-box">
        <div class="summary-item" style="flex: 2; text-align: left;">
            <div class="label">Summary</div>
            <div style="font-size: 11pt; margin-top: 10px;">
                Your organization receives a <strong>{{ "%.0f"|format(discount_percent) }}% discount</strong> on research computing services.
                This statement reflects <strong>${{ "%.2f"|format(total_discount) }}</strong> in savings.
            </div>
        </div>
        <div class="summary-item">
            <div class="label">Amount Due</div>
            <div class="value final">${{ "%.2f"|format(total_cost) }}</div>
        </div>
    </div>
    {% else %}
    <div class="summary-box">
        <div class="summary-item" style="flex: 1; text-align: right;">
            <div class="label">Total Amount Due</div>
            <div class="value final">${{ "%.2f"|format(total_cost) }}</div>
        </div>
    </div>
    {% endif %}

    <div class="footer">
        <p>This statement was generated automatically. For questions, please contact {{ contact_email }}.</p>
        <p>Generated: {{ generated_at }}</p>
    </div>
</body>
</html>
"""


def get_template_env(config: Config) -> Environment:
    """Get Jinja2 template environment."""
    # Check for custom templates directory
    templates_dir = Path("templates")
    if templates_dir.exists():
        return Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    # Use built-in templates
    from jinja2 import BaseLoader

    class StringLoader(BaseLoader):
        def get_source(self, environment, template):
            if template == "statement.html":
                return DEFAULT_STATEMENT_TEMPLATE, None, lambda: True
            raise Exception(f"Template not found: {template}")

    return Environment(loader=StringLoader(), autoescape=select_autoescape(["html", "xml"]))


def generate_pdf_statement(
    period: str,
    pi_email: str,
    project_summary: ProjectSummary,
    config: Config,
) -> Path:
    """Generate a PDF statement for a project.

    Args:
        period: Billing period (YYYY-MM).
        pi_email: PI's email address.
        project_summary: Project charges summary.
        config: Application configuration.

    Returns:
        Path to generated PDF file.
    """
    from datetime import datetime
    from weasyprint import HTML

    env = get_template_env(config)
    template = env.get_template("statement.html")

    # Render HTML
    html_content = template.render(
        period=period,
        pi_email=pi_email,
        project_id=project_summary.project_id,
        fund_org=project_summary.fund_org,
        total_list_cost=project_summary.total_list_cost,
        total_cost=project_summary.total_cost,
        total_discount=project_summary.total_discount,
        discount_percent=project_summary.discount_percent,
        service_breakdown=project_summary.service_breakdown,
        service_list_breakdown=project_summary.service_list_breakdown,
        charges=project_summary.charges,
        organization_name=config.email.from_name if config.email else "Research Computing",
        contact_email=config.email.from_address if config.email else "support@example.edu",
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    # Generate PDF
    safe_project_id = project_summary.project_id.replace("/", "_").replace("\\", "_")
    safe_pi = pi_email.split("@")[0]
    pdf_filename = f"{period}_{safe_pi}_{safe_project_id}.pdf"
    pdf_path = config.output.pdf_dir / pdf_filename

    HTML(string=html_content).write_pdf(pdf_path)

    return pdf_path

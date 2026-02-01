"""Email HTML generation."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import Config
from ..processing.aggregator import PISummary

# Default email template
DEFAULT_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            font-size: 14px;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }
        h1 {
            color: #2c3e50;
            font-size: 24px;
            margin-bottom: 20px;
        }
        .summary-box {
            background: #f8f9fa;
            border-left: 4px solid #3498db;
            padding: 15px;
            margin: 20px 0;
        }
        .summary-box .total {
            font-size: 28px;
            color: #27ae60;
            font-weight: bold;
        }
        .summary-box .list-price {
            font-size: 16px;
            color: #7f8c8d;
            text-decoration: line-through;
        }
        .summary-box .savings {
            font-size: 14px;
            color: #27ae60;
            margin-top: 5px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th {
            background: #2c3e50;
            color: white;
            padding: 10px;
            text-align: left;
        }
        td {
            padding: 10px;
            border-bottom: 1px solid #ecf0f1;
        }
        tr:nth-child(even) {
            background: #f8f9fa;
        }
        .amount {
            text-align: right;
            font-family: monospace;
        }
        .discount {
            text-align: right;
            font-family: monospace;
            color: #27ae60;
        }
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ecf0f1;
            font-size: 12px;
            color: #7f8c8d;
        }
        .note {
            background: #fff3cd;
            border: 1px solid #ffc107;
            border-radius: 4px;
            padding: 10px;
            margin: 20px 0;
        }
        .savings-note {
            background: #d4edda;
            border: 1px solid #28a745;
            border-radius: 4px;
            padding: 10px;
            margin: 20px 0;
            color: #155724;
        }
    </style>
</head>
<body>
    <h1>Research Computing Charges - {{ period }}</h1>

    <p>Dear Researcher,</p>

    <p>Please find below a summary of your research computing charges for {{ period }}.</p>

    <div class="summary-box">
        <div>Total Charges</div>
        {% if total_discount > 0 %}
        <div class="list-price">${{ "%.2f"|format(total_list_cost) }}</div>
        {% endif %}
        <div class="total">${{ "%.2f"|format(total_cost) }}</div>
        {% if total_discount > 0 %}
        <div class="savings">You saved ${{ "%.2f"|format(total_discount) }} ({{ "%.0f"|format(discount_percent) }}% discount)</div>
        {% endif %}
        <div>{{ project_count }} project(s)</div>
    </div>

    {% if total_discount > 0 %}
    <div class="savings-note">
        <strong>Institutional Discount Applied:</strong> Your organization receives negotiated rates on research computing services.
        This billing period reflects <strong>${{ "%.2f"|format(total_discount) }}</strong> in savings compared to list prices.
    </div>
    {% endif %}

    <h2>Charges by Project</h2>
    <table>
        <thead>
            <tr>
                <th>Project</th>
                <th>Fund/Org</th>
                {% if total_discount > 0 %}
                <th class="amount">List Price</th>
                <th class="discount">Discount</th>
                {% endif %}
                <th class="amount">Amount</th>
            </tr>
        </thead>
        <tbody>
            {% for project_id, project in projects.items() %}
            <tr>
                <td>{{ project_id }}</td>
                <td>{{ project.fund_org or 'N/A' }}</td>
                {% if total_discount > 0 %}
                <td class="amount">${{ "%.2f"|format(project.total_list_cost) }}</td>
                <td class="discount">{% if project.total_discount > 0 %}-${{ "%.2f"|format(project.total_discount) }}{% else %}-{% endif %}</td>
                {% endif %}
                <td class="amount">${{ "%.2f"|format(project.total_cost) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <p>Detailed statements for each project are attached as PDF files. These can be used for grant spending justifications.</p>

    <div class="note">
        <strong>Note:</strong> If you have questions about these charges or believe there is an error,
        please contact us at {{ contact_email }}.
    </div>

    <div class="footer">
        <p>This is an automated message from {{ organization_name }}.</p>
        <p>Please do not reply directly to this email.</p>
    </div>
</body>
</html>
"""


def get_template_env(config: Config) -> Environment:
    """Get Jinja2 template environment."""
    templates_dir = Path("templates")
    if templates_dir.exists():
        return Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    from jinja2 import BaseLoader

    class StringLoader(BaseLoader):
        def get_source(self, environment, template):
            if template == "email_summary.html":
                return DEFAULT_EMAIL_TEMPLATE, None, lambda: True
            raise Exception(f"Template not found: {template}")

    return Environment(loader=StringLoader(), autoescape=select_autoescape(["html", "xml"]))


def generate_email_html(
    period: str,
    pi_summary: PISummary,
    config: Config,
) -> str:
    """Generate HTML email body for a PI.

    Args:
        period: Billing period (YYYY-MM).
        pi_summary: PI's charges summary.
        config: Application configuration.

    Returns:
        HTML string for email body.
    """
    env = get_template_env(config)
    template = env.get_template("email_summary.html")

    return template.render(
        period=period,
        pi_email=pi_summary.pi_email,
        total_list_cost=pi_summary.total_list_cost,
        total_cost=pi_summary.total_cost,
        total_discount=pi_summary.total_discount,
        discount_percent=pi_summary.discount_percent,
        project_count=pi_summary.project_count,
        projects=pi_summary.projects,
        organization_name=config.email.from_name if config.email else "Research Computing",
        contact_email=config.email.from_address if config.email else "support@example.edu",
    )

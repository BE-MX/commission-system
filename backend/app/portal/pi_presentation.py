"""Explicit customer-visible commercial PI header; source IDs remain private."""
FIELDS = ("invoice_no", "customer_name", "invoice_date", "express_channel", "contact_email",
          "sales_user_name", "sales_phone", "sales_email", "packaging_quantity")


def capture(invoice):
    return {key:(invoice.invoice_date.isoformat() if key == "invoice_date" else getattr(invoice,key)) for key in FIELDS}


def project(snapshot):
    return {key:snapshot.get(key) for key in FIELDS}

from io import BytesIO
from unittest.mock import patch

import datetime
from decimal import Decimal
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from .models import Customer, Invoice, Quote, Transaction
from .receipt_ocr import extract_receipt_image, parse_receipt_text


class AdminDashboardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_dashboard_shows_metrics_and_model_app_list(self):
        customer = Customer.objects.create(
            name="Dashboard Test",
            email="dashboard-test@example.com",
        )
        quote = Quote.objects.create(
            customer=customer,
            service_type="Lawn Maintenance",
            estimated_total="42.50",
            status="pending",
        )
        Invoice.objects.create(
            customer=customer,
            due_date="2026-12-01",
            final_amount="42.50",
            status="unpaid",
        )

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pending Quote Requests")
        self.assertContains(response, "Outstanding Invoices")
        self.assertContains(response, "Unpaid Revenue Pipeline")
        metrics = {item["title"]: item["metric"] for item in response.context["kpi_metrics"]}
        self.assertEqual(metrics["Pending Quote Requests"], 1)
        self.assertEqual(metrics["Outstanding Invoices"], 1)
        self.assertEqual(metrics["Unpaid Revenue Pipeline"], "$42.50")
        self.assertContains(response, "$42.50")
        self.assertContains(response, reverse("admin:business_manager_customer_changelist"))
        self.assertContains(response, reverse("admin:business_manager_quote_changelist"))
        self.assertContains(response, reverse("admin:business_manager_invoice_changelist"))

        quote.status = "converted"
        quote.save(update_fields=["status"])
        invoice = Invoice.objects.get(customer=customer)
        invoice.status = "paid"
        invoice.save(update_fields=["status"])
        invoice.refresh_from_db()
        self.assertEqual(invoice.paid_date, timezone.localdate())
        invoice_income = Transaction.objects.get(source_invoice=invoice)
        self.assertEqual(invoice_income.amount, invoice.final_amount)
        self.assertEqual(invoice_income.transaction_type, "income")
        invoice.save()
        self.assertEqual(Transaction.objects.filter(source_invoice=invoice).count(), 1)

        invoice.final_amount = "47.50"
        invoice.save(update_fields=["final_amount"])
        invoice_income.refresh_from_db()
        self.assertEqual(invoice_income.amount, Decimal("47.50"))

        response = self.client.get(reverse("admin:index"))
        metrics = {item["title"]: item["metric"] for item in response.context["kpi_metrics"]}
        self.assertEqual(metrics["Pending Quote Requests"], 0)
        self.assertEqual(metrics["Outstanding Invoices"], 0)
        self.assertEqual(metrics["Unpaid Revenue Pipeline"], "$0.00")

        invoice.status = "unpaid"
        invoice.save(update_fields=["status"])
        self.assertFalse(Transaction.objects.filter(source_invoice=invoice).exists())

    @patch("business_manager.admin.extract_receipt_image")
    def test_receipt_ocr_admin_endpoint_returns_suggestions(self, extract_receipt_image):
        add_response = self.client.get(reverse("admin:business_manager_transaction_add"))
        self.assertEqual(add_response.status_code, 200)
        self.assertContains(add_response, "Read receipt")
        self.assertContains(add_response, "receipt_ocr.js")

        suggestions = {
            "transaction_type": "expense",
            "date": "2026-11-09",
            "merchant": "Garden Supply",
            "category": "Receipt purchase",
            "description": "Potting soil",
            "subtotal": "20.00",
            "tax_amount": "2.60",
            "amount": "22.60",
        }
        extract_receipt_image.return_value = suggestions
        receipt = SimpleUploadedFile("receipt.png", b"receipt image", content_type="image/png")

        response = self.client.post(
            reverse("admin:business_manager_transaction_receipt_ocr"),
            {"receipt": receipt},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fields"], suggestions)
        extract_receipt_image.assert_called_once()

    def test_dashboard_summarizes_current_month_transactions(self):
        today = timezone.localdate()
        previous_month = today.replace(day=1) - datetime.timedelta(days=1)
        Transaction.objects.create(
            transaction_type="income",
            date=today,
            category="Service payment",
            description="Mowing",
            amount="250.00",
        )
        Transaction.objects.create(
            transaction_type="expense",
            date=today,
            category="Fuel",
            amount="40.00",
        )
        Transaction.objects.create(
            transaction_type="income",
            date=previous_month,
            category="Service payment",
            amount="900.00",
        )

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        metrics = {item["title"]: item["metric"] for item in response.context["kpi_metrics"]}
        self.assertEqual(metrics["Income This Month"], "$250.00")
        self.assertEqual(metrics["Expenses This Month"], "$40.00")
        self.assertEqual(metrics["Net This Month"], "$210.00")
        self.assertContains(response, "Recent Income &amp; Expenses")
        self.assertContains(response, "Mowing")
        self.assertContains(response, reverse("admin:business_manager_transaction_add"))
        self.assertContains(response, reverse("admin:business_manager_transaction_changelist"))

    @patch("business_manager.admin.extract_receipt_image")
    def test_receipt_ocr_admin_endpoint_returns_suggestions(self, extract_receipt_image):
        suggestions = {
            "transaction_type": "expense",
            "date": "2026-11-09",
            "merchant": "Garden Supply",
            "category": "Receipt purchase",
            "description": "Potting soil",
            "subtotal": "20.00",
            "tax_amount": "2.60",
            "amount": "22.60",
        }
        extract_receipt_image.return_value = suggestions
        receipt = SimpleUploadedFile("receipt.png", b"receipt image", content_type="image/png")

        response = self.client.post(
            reverse("admin:business_manager_transaction_receipt_ocr"),
            {"receipt": receipt},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fields"], suggestions)
        extract_receipt_image.assert_called_once()


class ReceiptTextParserTests(SimpleTestCase):
    def test_receipt_url_uses_the_admin_only_file_route(self):
        transaction = Transaction(receipt="receipts/2026/11/receipt.png")

        self.assertEqual(
            transaction.receipt.url,
            reverse(
                "admin:business_manager_transaction_receipt_file",
                args=["receipts/2026/11/receipt.png"],
            ),
        )

    def test_parses_receipt_totals_date_merchant_and_items(self):
        parsed = parse_receipt_text(
            """GREEN GARDEN SUPPLY
            11/09/2026
            Potting Soil 12.99
            Garden Gloves 7.01
            Subtotal 20.00
            HST 2.60
            TOTAL 22.60"""
        )

        self.assertEqual(parsed["date"], "2026-11-09")
        self.assertEqual(parsed["merchant"], "GREEN GARDEN SUPPLY")
        self.assertEqual(parsed["description"], "Potting Soil, Garden Gloves")
        self.assertEqual(parsed["subtotal"], "20.00")
        self.assertEqual(parsed["tax_amount"], "2.60")
        self.assertEqual(parsed["amount"], "22.60")
        self.assertEqual(parsed["transaction_type"], "expense")

    @patch("pytesseract.image_to_string")
    def test_extracts_receipt_fields_from_uploaded_image(self, image_to_string):
        image_buffer = BytesIO()
        Image.new("RGB", (200, 100), color="white").save(image_buffer, format="PNG")
        image = SimpleUploadedFile(
            "receipt.png",
            image_buffer.getvalue(),
            content_type="image/png",
        )
        image_to_string.return_value = (
            "GREEN GARDEN SUPPLY\n11/09/2026\nPotting Soil 12.99\n"
            "Subtotal 12.99\nHST 1.69\nTOTAL 14.68"
        )

        result = extract_receipt_image(image)

        self.assertEqual(result["merchant"], "GREEN GARDEN SUPPLY")
        self.assertEqual(result["date"], "2026-11-09")
        self.assertEqual(result["description"], "Potting Soil")
        self.assertEqual(result["subtotal"], "12.99")
        self.assertEqual(result["tax_amount"], "1.69")
        self.assertEqual(result["amount"], "14.68")
        image_to_string.assert_called_once()

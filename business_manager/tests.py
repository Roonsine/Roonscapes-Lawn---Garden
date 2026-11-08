from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import Customer, Invoice, Quote


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

        response = self.client.get(reverse("admin:index"))
        metrics = {item["title"]: item["metric"] for item in response.context["kpi_metrics"]}
        self.assertEqual(metrics["Pending Quote Requests"], 0)
        self.assertEqual(metrics["Outstanding Invoices"], 0)
        self.assertEqual(metrics["Unpaid Revenue Pipeline"], "$0.00")

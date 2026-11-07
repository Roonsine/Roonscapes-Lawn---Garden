import datetime
from django.contrib import admin
from django.contrib import messages
from django.utils.crypto import get_random_string
from .models import Customer, Quote, Invoice
from unfold.admin import ModelAdmin

# Register your models here.
@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    """Admin configuration for managing your client directory"""
    list_display = ('name', 'email', 'phone', 'created_at')
    search_fields = ('name', 'email', 'phone', 'address')
    list_per_page = 25

@admin.register(Quote)
class QuoteAdmin(ModelAdmin):
    """Admin configuration for viewing and processing customer quotes."""
    list_display = ('id', 'customer', 'service_type', 'estimated_square_footage', 'estimated_total', 'status', 'created_at')
    list_filter = ('status', 'service_type', 'created_at')
    search_fields = ('customer__name', 'customer__email', 'service_type')
    ordering = ('-created_at',)
    
    # Registers your custom click action in the drop-down menu
    actions = ['convert_quotes_to_invoices']

    @admin.action(description="Convert selected pending quotes to unpaid invoices")
    def convert_quotes_to_invoices(self, request, queryset):
        """Action method that batch converts pending estimates into official records."""
        # Only process quotes that are currently marked 'pending'
        pending_quotes = queryset.filter(status='pending')
        converted_count = 0

        for quote in pending_quotes:
            # 1. Generate an invoice record tied to this user and estimate
            Invoice.objects.create(
                customer=quote.customer,
                originating_quote=quote,
                due_date=datetime.date.today() + datetime.timedelta(days=14), # 14-day payment window
                final_amount=quote.estimated_total,
                status='unpaid'
            )
            
            # 2. Progress the quote stage tracking status
            quote.status = 'converted'
            quote.save()
            converted_count += 1

        if converted_count > 0:
            self.message_user(
                request, 
                f"Successfully processed {converted_count} quote(s) into actionable invoices.",
                messages.SUCCESS
            )
        else:
            self.message_user(
                request, 
                "No invoices were created. Make sure the quotes you selected are still marked as 'Pending Review'.",
                messages.WARNING
            )


@admin.register(Invoice)
class InvoiceAdmin(ModelAdmin):
    """Admin configuration for processing bills, tracking payments, and auditing revenue."""
    list_display = ('invoice_number', 'customer', 'final_amount', 'status', 'due_date', 'issue_date')
    list_filter = ('status', 'due_date', 'issue_date')
    search_fields = ('invoice_number', 'customer__name', 'customer__email')
    readonly_fields = ('invoice_number', 'issue_date', 'created_at')
    ordering = ('-issue_date',)
    
    # Organizing detailed form layouts for when you view or manually type out an invoice
    fieldsets = [
        ('Core Parameters', {
            'fields': ('invoice_number', 'customer', 'originating_quote')
        }),
        ('Financial Terms', {
            'fields': ('final_amount', 'status', 'due_date')
        }),
        ('System Timestamps', {
            'fields': ('issue_date', 'created_at'),
            'classes': ('collapse',) # Hides section under a dropdown toggler
        }),
    ]
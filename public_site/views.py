from django.shortcuts import render, redirect
from django.contrib import messages
from business_manager.models import Customer, Quote
from decimal import Decimal
import math

# Create your views here.
def home_page(request):
    if request.method == "POST":
        # 1. Capture the fields from the upgraded HTML form.
        name = request.POST.get('name')
        email = request.POST.get('email').strip().lower()
        phone = request.POST.get('phone')
        address = request.POST.get('address')

        service_type = request.POST.get('service_type', 'Lawn Maintenance')
        sq_ft = request.POST.get('sq_ft', '0')
        include_edging = request.POST.get('include_edging') == 'yes'
        weeding_hours = int(request.POST.get('weeding_hours', 0))
        notes = request.POST.get('notes', '')

        try:
            sq_ft = int(sq_ft)
        except (ValueError, TypeError):
            sq_ft = 0

        try:
            weeding_hours = int(weeding_hours)
        except (ValueError, TypeError):
            weeding_hours = 0


        # 2. Get or create the customer profile using their email as a unique identifier.
        customer, created = Customer.objects.get_or_create(
            email = email,
            defaults={
                'name': name,
                'phone': phone,
                'address': address
            }
        )

        calculated_total = Decimal('0.00')
        summary_lines = []

        # 3. Run backend calculations for estimates.
        if service_type == "Lawn Maintenance":
            # Rule: Basic Cut is $35 up to 5000 sq ft, then $5 per 1000 sq ft over
            if sq_ft <= 5000:
                calculated_total += Decimal('35.00')
            else:
                over_sqft = sq_ft - 5000
                intervals = math.ceil(over_sqft / 1000)
                calculated_total += Decimal('35.00') + (Decimal(str(intervals)) * Decimal('5.00'))
            summary_lines.append("Basic Cut (Mow/Blow)")

            # Rule: Edging is a flat $10, plus $5 per 1000 sq ft over 5000
            if include_edging:
                calculated_total += Decimal('10.00')
                if sq_ft > 5000:
                    over_sqft = sq_ft - 5000
                    intervals = math.ceil(over_sqft / 1000)
                    calculated_total += Decimal(str(intervals)) * Decimal('5.00')
                summary_lines.append("Professional Edging Add-on")


        elif service_type == 'Weeding Maintenance':
            # Rule: Weeding/Routine Gardening is $40 per hour
            calculated_total += Decimal(str(weeding_hours)) * Decimal('40.00')
            summary_lines.append(f"Weeding & Routine Gardening ({weeding_hours} Hours)")

        # Combine items for service_type field in database entry
        final_service_desc = " + ".join(summary_lines) if summary_lines else service_type


        # 4. Save the new quote directly into your business manager tables
        Quote.objects.create(
            customer = customer,
            service_type = final_service_desc,
            estimated_square_footage = sq_ft,
            notes = notes,
            estimated_total = calculated_total,
            status = 'pending'
        )

        messages.success(request, f"Thanks {name}! Your estimate of ${calculated_total:,.2f} was submitted successfully!")
        return redirect('home')
    return render(request, 'public_site/index.html')
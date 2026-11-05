from django.shortcuts import render, redirect
from django.contrib import messages
from business_manager.models import Customer, Quote
from decimal import Decimal

# Create your views here.
def home_page(request):
    if request.method == "POST":
        # 1. Capture the fields from the upgraded HTML form.
        name = request.POST.get('name')
        email = request.POST.get('email').strip().lower()
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        service_type = request.POST.get('address')
        sq_ft_raw = request.POST.get('sq_ft', '0')
        notes = request.POST.get('notes', '')

        # Fallback to 0 if the user submits an empty of invalid square footage.
        try:
            sq_ft = int(sq_ft_raw)
        except:
            sq_ft = 0

        # 2. Get or create the customer profile using their email as a unique identifier.
        customer, created = Customer.objects.get_or_create(
            email = email,
            defaults={
                'name': name,
                'phone': phone,
                'address': address
            }
        )

        # 3. Simple backend calculator rules to generate the estimate
        if service_type == "Lawn Maintenance":
            rate = Decimal('0.15')
        elif service_type == "Landscaping Design":
            rate = Decimal('0.50')
        else:
            rate = Decimal('0.25') # Property cleanup or others

        calculated_total = sq_ft * rate

        # 4. Save the new quote directly into your business manager tables
        Quote.objects.create(
            customer = customer,
            service_type = service_type,
            estimated_square_footage = sq_ft,
            notes = notes,
            estimated_total = calculated_total,
            status = 'pending'
        )

        messages.success(request, f"Thanks {name}! Your estimate of ${calculated_total:,.2f} was submitted successfully!")
        return redirect('home')
    return render(request, 'public_site/index.html')
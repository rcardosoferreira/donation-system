from django.shortcuts import render
from django.template.loader import get_template
from django.core.mail import EmailMultiAlternatives
from .models import Donor, Donation, PaymentTransaction
from .configuration import Configuration
from maxipago import Maxipago
from maxipago.utils import payment_processors
from datetime import date
import logging
from random import randint
from dbwrapper.forms import FormDonor, FormDonation, FormPayment


import json

logger = logging.getLogger(__name__)


def donation_form(request):
    donor_form = FormDonor()
    donation_form = FormDonation()
    payment_form = FormPayment()
    
    if request.method == 'POST':
        donor_form = FormDonor(request.POST)
        tax_id = request.POST.get('CPF_field')

        if donor_form.is_valid():
            # tax id is required
            if not tax_id:
                raise Exception('donor_tax_id need to be provided')
            donor = Donor.objects.filter(tax_id=tax_id).first()

            # creates  a new donor
            if not donor:
                new_donor = Donor()
                new_donor.tax_id = tax_id
                new_donor.name = request.POST.get('name')
                new_donor.surname = request.POST.get('surname')
                new_donor.phone_number = request.POST.get('phone_number')
                new_donor.email = request.POST.get('email')
                if request.POST.get('is_anonymous'):
                    new_donor.is_anonymous = True
                else:
                    new_donor.is_anonymous = False
                new_donor.save()
                donor = new_donor

            # Payment
            new_payment = PaymentTransaction()
            new_payment.name_on_card = request.POST.get("name_on_card")
            new_payment.card_number = request.POST.get("card_number")
            new_payment.expiry_date_month = request.POST.get("expiry_date_month")
            new_payment.expiry_date_year = request.POST.get("expiry_date_year")
            new_payment.card_code = request.POST.get("card_code")
            new_payment.save()

            # Donation
            new_donation = Donation()
            new_donation.value = request.POST.get('value')
            new_donation.donor_tax_id = donor.tax_id
            is_recurring = request.POST.get('is_recurring_field')
            print("Is recurring: {}".format(is_recurring=='1'))
            if is_recurring == '1':
                new_donation.is_recurring = True
                new_donation.installments = u'12'
            else:
                new_donation.recurring = False
            new_donation.save()

            # Process payment
            config = Configuration()
            maxipago_id = config.get("payment", "merchant_id")
            maxipago_key = config.get("payment", "merchant_key")
            maxipago_sandbox = config.get("payment", "sandbox")
            print("Using Maxipago with customer {}".format(maxipago_id))
            maxipago = Maxipago(maxipago_id, maxipago_key, sandbox=maxipago_sandbox)

            REFERENCE = new_donation.donation_id
            payment_processor = payment_processors.TEST  # TEST or REDECARD
            print("Donation is recurring: {}".format(new_donation.is_recurring))

            if new_donation.is_recurring:
                response = maxipago.payment.create_recurring(
                    processor_id=payment_processor,
                    reference_num=REFERENCE,

                    billing_name=new_payment.name_on_card,
                    billing_phone=donor.phone_number,
                    billing_email=donor.email,
                    card_number=new_payment.card_number,
                    card_expiration_month=new_payment.expiry_date_month,
                    card_expiration_year=new_payment.expiry_date_year,
                    card_cvv=new_payment.card_code,
                    charge_total=new_donation.value,
                    currency_code=u'BRL',

                    recurring_action=u'new',
                    recurring_start=date.today().strftime('%Y-%m-%d'),
                    recurring_frequency=u'1',
                    recurring_period=u'monthly',
                    recurring_installments=new_donation.installments,
                    recurring_failure_threshold=u'2',
                )
            else:
                response = maxipago.payment.direct(
                    processor_id=payment_processor,
                    reference_num=REFERENCE,
                    billing_name=new_payment.name_on_card,
                    billing_phone=donor.phone_number,
                    billing_email=donor.email,
                    card_number=new_payment.card_number,
                    card_expiration_month=new_payment.expiry_date_month,
                    card_expiration_year=new_payment.expiry_date_year,
                    card_cvv=new_payment.card_code,
                    charge_total=new_donation.value,
                )

            print("Response code: {}".format(response.response_code))
            print("Response authorized: {}".format(response.authorized))
            print("Response captured: {}".format(response.captured))
            if response.authorized and response.captured:
                donation = Donation.objects.get(donation_id=new_donation.donation_id)
                donation.order_id = response.order_id
                donation.nsu_id = response.transaction_id
                donation.save()

                d = {'first_name': donor.name,
                     'value': new_donation.value,
                     'is_recurring': donation.is_recurring}

                plaintext = get_template('dbwrapper/successful_donation_email.txt')
                html_template = get_template('dbwrapper/successful_donation_email.html')

                subject = 'Obrigado pela sua contribuição!'
                text_content = plaintext.render(d)
                html_content = html_template.render(d)

                msg = EmailMultiAlternatives(
                    subject,
                    text_content,
                    'no-reply@amigosdapoli.com.br',
                    ['no-reply@amigosdapoli.com.br'],)
                msg.attach_alternative(html_content, "text/html")
                msg.send(fail_silently=True)
                return render(request, 'dbwrapper/successful_donation.html')
            else:
                    raise Exception('Payment not captured')
                # update donation with failed


    return render(request, 'dbwrapper/donation_form.html', {'donor_form':donor_form,'donation_form':donation_form, 'payment_form':payment_form})


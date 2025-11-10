# core/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.core.validators import MinValueValidator

# Class for different types of users
class User(AbstractUser):
    # Roles for authorization gates
    ROLE_PIN = 'PIN'
    ROLE_CV = 'CV'
    ROLE_CSR = 'CSR'
    ROLE_ADMIN = 'ADMIN'
    ROLE_CHOICES = [
        (ROLE_PIN, 'Person in Need'),
        (ROLE_CV, 'Corporate Volunteer'),
        (ROLE_CSR, 'CSR Representative'),
        (ROLE_ADMIN, 'Platform Admin'),
    ]

    # Extra fields shared by everyone
    full_name = models.CharField(max_length=120)
    date_of_birth = models.DateField(null=True, blank=True)
    home_address = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    # Company-only fields (CV/CSR)
    company_name = models.CharField(max_length=120, blank=True)
    company_id = models.CharField(max_length=60, blank=True)
    company_email = models.EmailField(blank=True)

    def __str__(self):
        return f"{self.username} ({self.role})"

class PINPreference(models.Model):
    # Only 1 row per PIN
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='pin_pref')
    preferred_language = models.CharField(max_length=60, blank=True)
    preferred_volunteer_gender = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"Preferences for {self.user.username}"

class ServiceRequest(models.Model):
    # What service is needed?
    SERVICE_CHOICES = [
        ('HEALTHCARE', 'Healthcare'),
        ('ESCORT', 'Escort'),
        ('THERAPY_ESCORT', 'Therapy Escort'),
        ('DIALYSIS_ESCORT', 'Dialysis Escort'),
        ('VACCINE_ESCORT', 'Vaccination / Check-Up Escort'),
        ('MOBILITY_ESCORT', 'Mobility Assistance Escort'),
        ('COMMUNITY_ESCORT', 'Community Event Escort'),
    ]

    STATUS_PENDING = 'PENDING'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_COMPLETED, 'Completed'),
    ]

    request_id = models.CharField(max_length=20, unique=True, editable=False)
    pin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='requests')
    service_type = models.CharField(max_length=30, choices=SERVICE_CHOICES)
    appointment_date = models.DateTimeField()
    pickup_location = models.CharField(max_length=255)
    service_location = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    date_created = models.DateTimeField(auto_now_add=True)

    # simple counters; we also store detailed rows in RequestView/Shortlist
    views = models.PositiveIntegerField(default=0)
    shortlists = models.PositiveIntegerField(default=0)

    def save(self, *args, **kwargs):
        # Auto-generate human-friendly ID like RQ-2025-00001
        if not self.request_id:
            now = timezone.now()
            prefix = f"RQ-{now.year}-"
            # naive incremental tail; for prod use a separate sequence
            count = ServiceRequest.objects.filter(request_id__startswith=prefix).count() + 1
            self.request_id = f"{prefix}{count:05d}"
        super().save(*args, **kwargs)

    def duplicate(self, new_appointment_dt):
        # Create a new copy with new ID and Date Created
        copy = ServiceRequest.objects.create(
            pin=self.pin,
            service_type=self.service_type,
            appointment_date=new_appointment_dt,
            pickup_location=self.pickup_location,
            service_location=self.service_location,
            description=self.description,
        )
        return copy

    def __str__(self):
        return f"{self.request_id} ({self.get_status_display()})"

class RequestView(models.Model):
    # When a CSR or CV opens a request, we log it and bump counter
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name='view_logs')
    viewer = models.ForeignKey(User, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now_add=True)

class Shortlist(models.Model):
    # When a CSR shortlists a request
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name='shortlist_logs')
    csr = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

class Match(models.Model):
    # Which CV is offered/accepted for which request
    request = models.OneToOneField(ServiceRequest, on_delete=models.CASCADE, related_name='match')
    cv = models.ForeignKey(User, on_delete=models.CASCADE, related_name='matches')
    offered_at = models.DateTimeField(default=timezone.now)
    accepted = models.BooleanField(null=True)  # None=pending, True=accepted, False=declined
    accepted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.request.request_id} → {self.cv.username} (accepted={self.accepted})"

class Message(models.Model):
    # Chat between PIN and CV; only allowed when request is ACTIVE
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    text = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

class FinancialClaim(models.Model):
    # A claim belongs to a request and CV
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name='claims')
    cv = models.ForeignKey(User, on_delete=models.CASCADE)

    # Simple two-step approvals
    approved_by_pin = models.BooleanField(default=False)
    approved_by_csr = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)

class ClaimItem(models.Model):
    claim = models.ForeignKey(FinancialClaim, on_delete=models.CASCADE, related_name='items')
    category = models.CharField(max_length=80)
    date_of_expense = models.DateField()
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    payment_method = models.CharField(max_length=40)
    description = models.TextField(blank=True)

class Receipt(models.Model):
    item = models.ForeignKey(ClaimItem, on_delete=models.CASCADE, related_name='receipts')
    image = models.ImageField(upload_to='receipts/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

class Dispute(models.Model):
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name='disputes')
    pin = models.ForeignKey(User, on_delete=models.CASCADE)
    incorrect_amount = models.BooleanField(default=False)
    incorrect_item = models.BooleanField(default=False)
    incorrect_receipt = models.BooleanField(default=False)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class OTPToken(models.Model):
    # Email OTP for sensitive profile edits
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timezone.timedelta(minutes=10)
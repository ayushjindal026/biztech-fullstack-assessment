import uuid
from django.db import models
from django.utils import timezone


class EmailJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(max_length=16, default="pending", db_index=True)
    failures = models.PositiveIntegerField(default=0)
    deferrals = models.PositiveIntegerField(default=0)
    due_at = models.DateTimeField(default=timezone.now, db_index=True)
    lease_until = models.DateTimeField(null=True)
    lease_token = models.UUIDField(null=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SendAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(EmailJob, related_name="attempts", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=32, default="uncertain")


class DeadLetter(models.Model):
    job = models.OneToOneField(EmailJob, on_delete=models.CASCADE)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

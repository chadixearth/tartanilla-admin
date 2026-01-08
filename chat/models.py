from django.db import models
from django.contrib.auth.models import User

class ChatMessage(models.Model):
    sender = models.CharField(max_length=100, default='Test User')
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    room = models.CharField(max_length=50, default='test-room')
    
    class Meta:
        ordering = ['timestamp']
    
    def __str__(self):
        return f"{self.sender}: {self.message[:50]}"

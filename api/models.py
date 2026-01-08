from django.db import models

class Review(models.Model):
    """Base review model for package reviews"""
    package_id = models.CharField(max_length=255)
    booking_id = models.CharField(max_length=255)
    reviewer_id = models.CharField(max_length=255)
    rating = models.IntegerField()
    comment = models.TextField(blank=True)
    is_anonymous = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'package_reviews'
    
    def get_reviewer_display_name(self):
        """Return display name for reviewer based on anonymous setting"""
        if self.is_anonymous:
            return "Anonymous"
        # In a real implementation, you'd fetch the reviewer's name from the users table
        return "Customer"

class DriverReview(models.Model):
    """Driver review model"""
    driver_id = models.CharField(max_length=255)
    booking_id = models.CharField(max_length=255)
    reviewer_id = models.CharField(max_length=255)
    rating = models.IntegerField()
    comment = models.TextField(blank=True)
    is_anonymous = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'driver_reviews'
    
    def get_reviewer_display_name(self):
        """Return display name for reviewer based on anonymous setting"""
        if self.is_anonymous:
            return "Anonymous"
        return "Customer"
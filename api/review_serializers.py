from rest_framework import serializers
from .models import Review, DriverReview

class ReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Review
        fields = ['id', 'rating', 'comment', 'is_anonymous', 'reviewer_name', 'created_at']
    
    def get_reviewer_name(self, obj):
        return obj.get_reviewer_display_name()

class DriverReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField()
    
    class Meta:
        model = DriverReview
        fields = ['id', 'rating', 'comment', 'is_anonymous', 'reviewer_name', 'created_at']
    
    def get_reviewer_name(self, obj):
        return obj.get_reviewer_display_name()
from rest_framework import serializers

class TourPackageViewSerializer(serializers.Serializer):
    """Serializer for viewing tour packages (read-only operations)"""
    id = serializers.UUIDField(read_only=True)
    package_name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    price = serializers.FloatField(read_only=True)
    pickup_location = serializers.CharField(read_only=True)
    destination = serializers.CharField(read_only=True)
    pickup_lat = serializers.FloatField(read_only=True, allow_null=True)
    pickup_lng = serializers.FloatField(read_only=True, allow_null=True)
    dropoff_lat = serializers.FloatField(read_only=True, allow_null=True)
    dropoff_lng = serializers.FloatField(read_only=True, allow_null=True)
    route = serializers.CharField(read_only=True, allow_null=True)
    duration_hours = serializers.IntegerField(read_only=True, allow_null=True)
    max_pax = serializers.IntegerField(read_only=True, allow_null=True)
    available_days = serializers.ListField(
        child=serializers.CharField(),
        read_only=True
    )
    expiration_date = serializers.CharField(read_only=True)  # Formatted date string
    photos = serializers.ListField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    
    # Review aggregation fields
    average_rating = serializers.FloatField(read_only=True, default=0.0)
    reviews_count = serializers.IntegerField(read_only=True, default=0)
    reviews = serializers.ListField(read_only=True, default=list)

class TourPackageResponseSerializer(serializers.Serializer):
    """Serializer for API response structure"""
    success = serializers.BooleanField()
    data = TourPackageViewSerializer(many=True, required=False)
    error = serializers.CharField(required=False)

# Booking Serializers
class BookingCreateSerializer(serializers.Serializer):
    """Serializer for creating bookings"""
    package_id = serializers.UUIDField(required=True)
    customer_id = serializers.UUIDField(required=True)
    booking_date = serializers.DateField(required=True)
    pickup_time = serializers.TimeField(required=False, default='09:00:00')
    number_of_pax = serializers.IntegerField(required=True, min_value=1)
    special_requests = serializers.CharField(required=False, allow_blank=True, default='')
    contact_number = serializers.CharField(required=False, allow_blank=True, default='')
    pickup_address = serializers.CharField(required=False, allow_blank=True, default='')

class BookingUpdateSerializer(serializers.Serializer):
    """Serializer for updating bookings"""
    package_id = serializers.UUIDField(required=False)
    customer_id = serializers.UUIDField(required=False)
    booking_date = serializers.DateField(required=False)
    pickup_time = serializers.TimeField(required=False)
    number_of_pax = serializers.IntegerField(required=False, min_value=1)
    special_requests = serializers.CharField(required=False, allow_blank=True)
    contact_number = serializers.CharField(required=False, allow_blank=True)
    pickup_address = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(
        choices=['pending', 'confirmed', 'cancelled', 'completed'],
        required=False
    )

class BookingViewSerializer(serializers.Serializer):
    """Serializer for viewing bookings (read-only operations)"""
    id = serializers.UUIDField(read_only=True)
    package_id = serializers.UUIDField(read_only=True)
    customer_id = serializers.UUIDField(read_only=True)
    booking_date = serializers.DateField(read_only=True)
    pickup_time = serializers.TimeField(read_only=True)
    number_of_pax = serializers.IntegerField(read_only=True)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    special_requests = serializers.CharField(read_only=True)
    contact_number = serializers.CharField(read_only=True)
    pickup_address = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    booking_reference = serializers.CharField(read_only=True)
    package_name = serializers.CharField(read_only=True)
    package_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    customer_name = serializers.CharField(read_only=True)
    customer_email = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

class BookingResponseSerializer(serializers.Serializer):
    """Serializer for booking API response structure"""
    success = serializers.BooleanField()
    data = BookingViewSerializer(required=False)
    error = serializers.CharField(required=False)
    message = serializers.CharField(required=False)
    count = serializers.IntegerField(required=False)

class BookingStatsSerializer(serializers.Serializer):
    """Serializer for booking statistics"""
    total_bookings = serializers.IntegerField()
    status_counts = serializers.DictField(child=serializers.IntegerField())
    today_bookings = serializers.IntegerField()
    month_bookings = serializers.IntegerField()

class BookingStatsResponseSerializer(serializers.Serializer):
    """Serializer for booking stats API response structure"""
    success = serializers.BooleanField()
    data = BookingStatsSerializer(required=False)
    error = serializers.CharField(required=False)


# EARNINGS AND SHARES SERIALIZERS

class EarningsSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    driver_name = serializers.CharField(required=False, allow_blank=True)
    booking_id = serializers.UUIDField()
    driver_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    earning_date = serializers.DateTimeField(read_only=True)


class PayoutSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    driver_id = serializers.UUIDField()
    driver_name = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    payout_date = serializers.DateTimeField(read_only=True)
    payout_method = serializers.CharField()
    status = serializers.ChoiceField(choices=[("pending", "pending"), ("released", "released")], default="pending")
    remarks = serializers.CharField(required=False, allow_blank=True)


class PayoutEarningsSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    driver_name = serializers.CharField(required=False, allow_blank=True)
    payout_id = serializers.UUIDField()
    earning_id = serializers.UUIDField()
    driver_id = serializers.UUIDField()
    share_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    status = serializers.ChoiceField(choices=[("pending", "pending"), ("released", "released")], default="pending")


# Custom Package Request Serializers
class CustomTourRequestSerializer(serializers.Serializer):
    """Serializer for custom tour requests (tourist input only)"""
    customer_id = serializers.UUIDField(required=True)
    destination = serializers.CharField(required=True, max_length=255)
    pickup_location = serializers.CharField(required=False, allow_blank=True)
    preferred_duration_hours = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=24)
    preferred_duration_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=59)
    number_of_pax = serializers.IntegerField(required=True, min_value=1, max_value=100)
    preferred_date = serializers.DateField(required=False, allow_null=True)
    special_requests = serializers.CharField(required=False, allow_blank=True)
    contact_number = serializers.CharField(required=True, max_length=20)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    
    def validate_contact_number(self, value):
        if not value or not any(c.isdigit() for c in value):
            raise serializers.ValidationError("Contact number must contain at least one digit")
        return value
    
    def validate(self, data):
        hours = data.get('preferred_duration_hours') or 0
        minutes = data.get('preferred_duration_minutes') or 0
        if hours == 0 and minutes == 0:
            raise serializers.ValidationError("Duration must be at least 1 minute")
        return data


class SpecialEventRequestSerializer(serializers.Serializer):
    """Serializer for special event requests (tourist input only)"""
    customer_id = serializers.UUIDField(required=True)
    event_type = serializers.CharField(required=True, max_length=100)  # wedding, birthday, corporate, etc.
    event_date = serializers.DateField(required=True)
    event_time = serializers.TimeField(required=False, allow_null=True)
    event_address = serializers.CharField(required=True, max_length=500)  # single address where event happens
    number_of_pax = serializers.IntegerField(required=True, min_value=1, max_value=100)
    special_requirements = serializers.CharField(required=False, allow_blank=True)
    contact_number = serializers.CharField(required=True, max_length=20)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    
    def validate_contact_number(self, value):
        if not value or not any(c.isdigit() for c in value):
            raise serializers.ValidationError("Contact number must contain at least one digit")
        return value


class RequestCreateSerializer(serializers.Serializer):
    """Main serializer for creating requests"""
    request_type = serializers.ChoiceField(
        choices=['custom_tour', 'special_event'],
        required=True
    )
    custom_tour_data = CustomTourRequestSerializer(required=False, allow_null=True)
    special_event_data = SpecialEventRequestSerializer(required=False, allow_null=True)

    def validate(self, data):
        """Validate that the correct data is provided based on request_type"""
        request_type = data.get('request_type')
        
        if request_type == 'custom_tour':
            if not data.get('custom_tour_data'):
                raise serializers.ValidationError("custom_tour_data is required when request_type is 'custom_tour'")
            # Remove special_event_data if provided
            data.pop('special_event_data', None)
        elif request_type == 'special_event':
            if not data.get('special_event_data'):
                raise serializers.ValidationError("special_event_data is required when request_type is 'special_event'")
            # Remove custom_tour_data if provided
            data.pop('custom_tour_data', None)
        
        return data


class CustomTourRequestViewSerializer(serializers.Serializer):
    """Serializer for viewing custom tour requests"""
    id = serializers.UUIDField(read_only=True)
    customer_id = serializers.UUIDField(read_only=True)
    customer_name = serializers.CharField(read_only=True)
    customer_email = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    
    # Tourist input fields
    destination = serializers.CharField(read_only=True)
    pickup_location = serializers.CharField(read_only=True)
    preferred_duration_hours = serializers.IntegerField(read_only=True)
    preferred_duration_minutes = serializers.IntegerField(read_only=True)
    number_of_pax = serializers.IntegerField(read_only=True)
    preferred_date = serializers.DateField(read_only=True)
    special_requests = serializers.CharField(read_only=True)
    contact_number = serializers.CharField(read_only=True)
    contact_email = serializers.CharField(read_only=True)
    
    # Admin-managed fields
    package_name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    approved_price = serializers.FloatField(read_only=True)
    available_days = serializers.ListField(read_only=True)
    
    # Driver assignment fields
    driver_id = serializers.UUIDField(read_only=True)
    driver_name = serializers.CharField(read_only=True)
    driver_assigned_at = serializers.DateTimeField(read_only=True)
    available_for_drivers = serializers.BooleanField(read_only=True)
    
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class SpecialEventRequestViewSerializer(serializers.Serializer):
    """Serializer for viewing special event requests"""
    id = serializers.UUIDField(read_only=True)
    customer_id = serializers.UUIDField(read_only=True)
    customer_name = serializers.CharField(read_only=True)
    customer_email = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    
    # Tourist input fields
    event_type = serializers.CharField(read_only=True)
    event_date = serializers.DateField(read_only=True)
    event_time = serializers.TimeField(read_only=True)
    event_address = serializers.CharField(read_only=True)
    number_of_pax = serializers.IntegerField(read_only=True)
    special_requirements = serializers.CharField(read_only=True)
    contact_number = serializers.CharField(read_only=True)
    contact_email = serializers.CharField(read_only=True)
    
    # Admin-managed fields
    approved_price_range = serializers.CharField(read_only=True)
    package_details = serializers.CharField(read_only=True)
    
    # Owner acceptance fields
    owner_id = serializers.UUIDField(read_only=True)
    owner_name = serializers.CharField(read_only=True)
    owner_accepted_at = serializers.DateTimeField(read_only=True)
    available_for_owners = serializers.BooleanField(read_only=True)
    
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class DriverSerializer(serializers.Serializer):
    """Serializer for driver data with profile image support"""
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    name = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    profile_photo_url = serializers.URLField(read_only=True, allow_null=True)
    profile_image = serializers.SerializerMethodField()
    
    def get_profile_image(self, obj):
        url = obj.get('profile_photo_url')
        return url.rstrip('?') if url else None

class ResponseSerializer(serializers.Serializer):
    """Serializer for API response structure"""
    success = serializers.BooleanField()
    data = serializers.DictField(required=False)
    error = serializers.CharField(required=False)
    message = serializers.CharField(required=False)
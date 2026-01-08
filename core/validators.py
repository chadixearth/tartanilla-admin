"""
Comprehensive input validators for all API endpoints
"""

import re
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import bleach

class InputValidator:
    """Centralized input validation for all API endpoints"""
    
    # Validation patterns
    PATTERNS = {
        'phone': r'^\+?63[0-9]{10}$|^09[0-9]{9}$',
        'name': r'^[a-zA-Z\s\-\.]{2,50}$',
        'username': r'^[a-zA-Z0-9_]{3,30}$',
        'password': r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[a-zA-Z\d@$!%*?&]{8,}$',
        'coordinates': r'^-?([1-8]?[0-9]\.{1}\d{1,6}$|90\.{1}0{1,6}$)$',
        'price': r'^\d+(\.\d{1,2})?$',
        'booking_id': r'^[a-zA-Z0-9\-]{10,50}$',
        'license_plate': r'^[A-Z0-9\-\s]{3,15}$',
    }
    
    # Dangerous patterns to block
    DANGEROUS_PATTERNS = [
        r'<script[^>]*>.*?</script>',
        r'javascript:',
        r'on\w+\s*=',
        r'<iframe[^>]*>.*?</iframe>',
        r'eval\s*\(',
        r'document\.',
        r'window\.',
        r'alert\s*\(',
        r'union\s+select',
        r'drop\s+table',
        r'delete\s+from',
        r'insert\s+into',
    ]
    
    @classmethod
    def validate_string(cls, value, field_name, min_length=1, max_length=255, pattern=None, required=True):
        """Validate string input with comprehensive checks"""
        if not required and (value is None or value == ''):
            return None
        
        if not isinstance(value, str):
            raise ValidationError(f"{field_name} must be a string")
        
        # Check for dangerous patterns
        value_lower = value.lower()
        for pattern_check in cls.DANGEROUS_PATTERNS:
            if re.search(pattern_check, value_lower, re.IGNORECASE):
                raise ValidationError(f"{field_name} contains invalid characters")
        
        # Length validation
        if len(value) < min_length:
            raise ValidationError(f"{field_name} must be at least {min_length} characters")
        
        if len(value) > max_length:
            raise ValidationError(f"{field_name} must be at most {max_length} characters")
        
        # Pattern validation
        if pattern and not re.match(pattern, value):
            raise ValidationError(f"{field_name} format is invalid")
        
        # Sanitize the value
        return bleach.clean(value.strip(), tags=[], attributes={}, strip=True)
    
    @classmethod
    def validate_email_field(cls, email, required=True):
        """Validate email with comprehensive checks"""
        if not required and (email is None or email == ''):
            return None
        
        if not isinstance(email, str):
            raise ValidationError("Email must be a string")
        
        email = email.strip().lower()
        
        try:
            validate_email(email)
        except ValidationError:
            raise ValidationError("Invalid email format")
        
        # Additional email security checks
        if len(email) > 254:
            raise ValidationError("Email is too long")
        
        return email
    
    @classmethod
    def validate_phone(cls, phone, required=True):
        """Validate Philippine phone numbers"""
        if not required and (phone is None or phone == ''):
            return None
        
        phone = cls.validate_string(phone, "Phone", pattern=cls.PATTERNS['phone'])
        
        # Normalize phone format
        if phone.startswith('09'):
            phone = '+63' + phone[1:]
        elif not phone.startswith('+63'):
            phone = '+63' + phone
        
        return phone
    
    @classmethod
    def validate_coordinates(cls, lat, lng):
        """Validate latitude and longitude coordinates"""
        try:
            lat = float(lat)
            lng = float(lng)
        except (ValueError, TypeError):
            raise ValidationError("Coordinates must be valid numbers")
        
        if not (-90 <= lat <= 90):
            raise ValidationError("Latitude must be between -90 and 90")
        
        if not (-180 <= lng <= 180):
            raise ValidationError("Longitude must be between -180 and 180")
        
        return lat, lng
    
    @classmethod
    def validate_price(cls, price, min_value=0, max_value=100000):
        """Validate price/monetary values"""
        if isinstance(price, str):
            if not re.match(cls.PATTERNS['price'], price):
                raise ValidationError("Invalid price format")
            try:
                price = Decimal(price)
            except InvalidOperation:
                raise ValidationError("Invalid price value")
        elif isinstance(price, (int, float)):
            price = Decimal(str(price))
        else:
            raise ValidationError("Price must be a number")
        
        if price < min_value:
            raise ValidationError(f"Price must be at least {min_value}")
        
        if price > max_value:
            raise ValidationError(f"Price cannot exceed {max_value}")
        
        return price
    
    @classmethod
    def validate_datetime(cls, dt_string, required=True):
        """Validate datetime strings"""
        if not required and (dt_string is None or dt_string == ''):
            return None
        
        if not isinstance(dt_string, str):
            raise ValidationError("Datetime must be a string")
        
        try:
            # Try multiple datetime formats
            formats = [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%d',
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(dt_string, fmt)
                except ValueError:
                    continue
            
            raise ValueError("No matching format")
            
        except ValueError:
            raise ValidationError("Invalid datetime format")
    
    @classmethod
    def validate_json_data(cls, data, required_fields=None, optional_fields=None):
        """Validate JSON data structure"""
        if not isinstance(data, dict):
            raise ValidationError("Data must be a JSON object")
        
        # Check required fields
        if required_fields:
            for field in required_fields:
                if field not in data:
                    raise ValidationError(f"Required field '{field}' is missing")
        
        # Validate allowed fields
        if required_fields or optional_fields:
            allowed_fields = set(required_fields or []) | set(optional_fields or [])
            for field in data.keys():
                if field not in allowed_fields:
                    raise ValidationError(f"Unknown field '{field}'")
        
        return data
    
    @classmethod
    def validate_booking_data(cls, data):
        """Validate booking request data"""
        required_fields = ['pickup_location', 'destination', 'scheduled_time', 'passenger_count']
        optional_fields = ['special_requests', 'contact_phone']
        
        data = cls.validate_json_data(data, required_fields, optional_fields)
        
        # Validate specific fields
        if 'pickup_location' in data:
            pickup = data['pickup_location']
            if not isinstance(pickup, dict) or 'lat' not in pickup or 'lng' not in pickup:
                raise ValidationError("Invalid pickup location format")
            data['pickup_location']['lat'], data['pickup_location']['lng'] = cls.validate_coordinates(
                pickup['lat'], pickup['lng']
            )
        
        if 'destination' in data:
            dest = data['destination']
            if not isinstance(dest, dict) or 'lat' not in dest or 'lng' not in dest:
                raise ValidationError("Invalid destination format")
            data['destination']['lat'], data['destination']['lng'] = cls.validate_coordinates(
                dest['lat'], dest['lng']
            )
        
        if 'scheduled_time' in data:
            data['scheduled_time'] = cls.validate_datetime(data['scheduled_time'])
        
        if 'passenger_count' in data:
            try:
                count = int(data['passenger_count'])
                if count < 1 or count > 20:
                    raise ValidationError("Passenger count must be between 1 and 20")
                data['passenger_count'] = count
            except (ValueError, TypeError):
                raise ValidationError("Passenger count must be a valid number")
        
        if 'contact_phone' in data:
            data['contact_phone'] = cls.validate_phone(data['contact_phone'], required=False)
        
        if 'special_requests' in data:
            data['special_requests'] = cls.validate_string(
                data['special_requests'], "Special requests", max_length=500, required=False
            )
        
        return data
    
    @classmethod
    def validate_user_data(cls, data, is_registration=False):
        """Validate user registration/update data"""
        if is_registration:
            required_fields = ['email', 'password', 'first_name', 'last_name']
            optional_fields = ['phone', 'address']
        else:
            required_fields = []
            optional_fields = ['email', 'first_name', 'last_name', 'phone', 'address']
        
        data = cls.validate_json_data(data, required_fields, optional_fields)
        
        # Validate specific fields
        if 'email' in data:
            data['email'] = cls.validate_email_field(data['email'], required=is_registration)
        
        if 'password' in data:
            data['password'] = cls.validate_string(
                data['password'], "Password", min_length=8, pattern=cls.PATTERNS['password']
            )
        
        if 'first_name' in data:
            data['first_name'] = cls.validate_string(
                data['first_name'], "First name", pattern=cls.PATTERNS['name']
            )
        
        if 'last_name' in data:
            data['last_name'] = cls.validate_string(
                data['last_name'], "Last name", pattern=cls.PATTERNS['name']
            )
        
        if 'phone' in data:
            data['phone'] = cls.validate_phone(data['phone'], required=False)
        
        if 'address' in data:
            data['address'] = cls.validate_string(
                data['address'], "Address", max_length=200, required=False
            )
        
        return data
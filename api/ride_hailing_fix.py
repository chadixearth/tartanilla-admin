def _record_ride_hailing_earnings(self, ride_data, driver_id):
    """Record ride hailing earnings to earnings table (100% to driver)"""
    try:
        total_fare = float(ride_data.get('total_fare', 0))
        if total_fare <= 0:
            return
        
        earnings_payload = {
            'booking_id': ride_data.get('id'),
            'driver_id': driver_id,
            'driver_name': ride_data.get('driver_name', 'Unknown'),
            'amount': total_fare,
            'total_amount': total_fare,
            'driver_earnings': total_fare,
            'admin_earnings': 0,
            'package_name': 'Ride Hailing',
            'booking_type': 'ridehailing',
            'earning_date': datetime.now().isoformat(),
            'status': 'completed',
            'created_at': datetime.now().isoformat()
        }
        
        supabase.table('earnings').insert(earnings_payload).execute()
        print(f"[RIDE_HAILING] Recorded earnings for ride {ride_data.get('id')}: ₱{total_fare} (Driver: ₱{total_fare})")
    except Exception as e:
        print(f"[RIDE_HAILING] Error recording earnings: {e}")

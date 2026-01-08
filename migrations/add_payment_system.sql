-- Migration script to add payment system to the booking platform

-- Add payment tracking fields to the bookings table
ALTER TABLE bookings 
ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50),
ADD COLUMN IF NOT EXISTS payment_reference VARCHAR(100),
ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;

-- Create payments table to track all payment transactions
CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_id UUID NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    payment_intent_id VARCHAR(100) UNIQUE NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'PHP',
    payment_method_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    paymongo_payment_id VARCHAR(100),
    paymongo_source_id VARCHAR(100),
    failure_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    paid_at TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_payments_booking_id ON payments(booking_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_payment_intent_id ON payments(payment_intent_id);
CREATE INDEX IF NOT EXISTS idx_bookings_payment_status ON bookings(payment_status);

-- Update existing bookings to have payment_status = 'paid' if they are already completed
UPDATE bookings 
SET payment_status = 'paid' 
WHERE status IN ('completed', 'driver_accepted', 'in_progress') 
AND payment_status IS NULL;

-- Update existing pending bookings to require payment
UPDATE bookings 
SET payment_status = 'pending' 
WHERE status = 'waiting_for_driver' 
AND payment_status IS NULL;

-- Add comments for documentation
COMMENT ON TABLE payments IS 'Tracks all payment transactions for bookings';
COMMENT ON COLUMN bookings.payment_status IS 'Payment status: pending, paid, failed, refunded';
COMMENT ON COLUMN bookings.payment_method IS 'Payment method used: gcash, grab_pay, paymaya, card';
COMMENT ON COLUMN bookings.payment_reference IS 'Reference number from payment gateway';
COMMENT ON COLUMN payments.payment_intent_id IS 'PayMongo payment intent ID';
COMMENT ON COLUMN payments.payment_method_type IS 'Type of payment method: gcash, grab_pay, paymaya, card';
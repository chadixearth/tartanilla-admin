-- Migration script to add refunds table for handling cancellation refunds

-- Create refunds table to track all refund requests
CREATE TABLE IF NOT EXISTS refunds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    refund_reference VARCHAR(50) UNIQUE NOT NULL,
    booking_id UUID NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL,
    driver_id UUID,
    amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    original_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    refund_percentage DECIMAL(5,2) DEFAULT 100.00,
    reason TEXT,
    status VARCHAR(20) DEFAULT 'requested',
    payment_method VARCHAR(50),
    refund_method VARCHAR(50) DEFAULT 'original_payment_method',
    cancelled_by VARCHAR(20),
    requested_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    completed_at TIMESTAMP,
    admin_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_refunds_booking_id ON refunds(booking_id);
CREATE INDEX IF NOT EXISTS idx_refunds_customer_id ON refunds(customer_id);
CREATE INDEX IF NOT EXISTS idx_refunds_status ON refunds(status);
CREATE INDEX IF NOT EXISTS idx_refunds_refund_reference ON refunds(refund_reference);
CREATE INDEX IF NOT EXISTS idx_refunds_requested_at ON refunds(requested_at);

-- Add refund tracking to bookings table
ALTER TABLE bookings 
ADD COLUMN IF NOT EXISTS refund_status VARCHAR(20) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS refund_amount DECIMAL(10,2) DEFAULT 0.00,
ADD COLUMN IF NOT EXISTS refund_requested_at TIMESTAMP;

-- Add comments for documentation
COMMENT ON TABLE refunds IS 'Tracks all refund requests and processing for cancelled bookings';
COMMENT ON COLUMN refunds.refund_reference IS 'Unique reference number for the refund (e.g., RF-20240101-ABCDE)';
COMMENT ON COLUMN refunds.amount IS 'Actual refund amount after applying cancellation policy';
COMMENT ON COLUMN refunds.original_amount IS 'Original booking amount before cancellation fees';
COMMENT ON COLUMN refunds.refund_percentage IS 'Percentage of original amount being refunded';
COMMENT ON COLUMN refunds.status IS 'Refund status: requested, approved, processing, completed, rejected';
COMMENT ON COLUMN refunds.cancelled_by IS 'Who cancelled the booking: customer, driver, admin, system';
COMMENT ON COLUMN refunds.refund_method IS 'How refund will be processed: original_payment_method, bank_transfer, cash, gcash';
COMMENT ON COLUMN bookings.refund_status IS 'Refund status for the booking: requested, approved, processing, completed';
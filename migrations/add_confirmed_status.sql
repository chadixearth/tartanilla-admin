-- Add 'confirmed' status to booking status constraint
-- This status is used after payment is completed but before trip starts

-- Drop the old constraint
ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_status_check;

-- Add new constraint that includes 'confirmed' status
ALTER TABLE bookings ADD CONSTRAINT bookings_status_check 
CHECK (status IN (
    'pending',                  -- Initial status when tourist creates booking
    'waiting_for_driver',       -- Deprecated but kept for compatibility
    'driver_assigned',          -- Driver has accepted the booking
    'confirmed',                -- Payment completed, booking confirmed
    'in_progress',              -- Trip has started
    'completed',                -- Trip completed successfully
    'cancelled',                -- Booking was cancelled
    'no_driver_available'       -- Timeout - no driver accepted within time limit
));

-- Update comment explaining the status flow
COMMENT ON COLUMN bookings.status IS 'Booking status flow: pending (initial) -> driver_assigned (driver accepts) -> confirmed (payment done) -> in_progress (trip started) -> completed (trip finished) OR cancelled (any time)';

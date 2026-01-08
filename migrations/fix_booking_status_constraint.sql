-- Fix booking status constraint to allow 'pending' status
-- This allows tourists to create bookings that wait for driver acceptance

-- Drop the old constraint if it exists
ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_status_check;

-- Add new constraint that includes 'pending' status
ALTER TABLE bookings ADD CONSTRAINT bookings_status_check 
CHECK (status IN (
    'pending',                  -- Initial status when tourist creates booking
    'waiting_for_driver',       -- Deprecated but kept for compatibility
    'driver_assigned',          -- Driver has accepted the booking
    'in_progress',              -- Trip has started
    'completed',                -- Trip completed successfully
    'cancelled',                -- Booking was cancelled
    'no_driver_available'       -- Timeout - no driver accepted within time limit
));

-- Add comment explaining the status flow
COMMENT ON COLUMN bookings.status IS 'Booking status: pending (initial) -> driver_assigned (driver accepts) -> in_progress (trip started) -> completed (trip finished) OR cancelled (any time)';

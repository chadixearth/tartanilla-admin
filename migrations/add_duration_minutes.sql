-- Add preferred_duration_minutes column to custom_tour_requests table
ALTER TABLE custom_tour_requests 
ADD COLUMN IF NOT EXISTS preferred_duration_minutes INTEGER DEFAULT 0;

-- Update existing records to have 0 minutes (they only have hours)
UPDATE custom_tour_requests 
SET preferred_duration_minutes = 0 
WHERE preferred_duration_minutes IS NULL;

-- Add comment
COMMENT ON COLUMN custom_tour_requests.preferred_duration_minutes IS 'Duration in minutes (0-59), used with preferred_duration_hours';

-- Add is_anonymous field to package_reviews table
ALTER TABLE package_reviews ADD COLUMN IF NOT EXISTS is_anonymous BOOLEAN DEFAULT FALSE;

-- Add is_anonymous field to driver_reviews table  
ALTER TABLE driver_reviews ADD COLUMN IF NOT EXISTS is_anonymous BOOLEAN DEFAULT FALSE;

-- Update existing reviews to have is_anonymous = FALSE (default behavior)
UPDATE package_reviews SET is_anonymous = FALSE WHERE is_anonymous IS NULL;
UPDATE driver_reviews SET is_anonymous = FALSE WHERE is_anonymous IS NULL;
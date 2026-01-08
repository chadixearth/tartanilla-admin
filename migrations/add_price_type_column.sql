-- Add price_type column to tourpackages table
ALTER TABLE tourpackages ADD COLUMN IF NOT EXISTS price_type TEXT DEFAULT 'per_person' CHECK (price_type IN ('per_person', 'per_hour', 'fixed'));

-- Update existing records to have default price_type
UPDATE tourpackages SET price_type = 'per_person' WHERE price_type IS NULL;

-- Create tour_itinerary table for step-by-step tour package details
CREATE TABLE IF NOT EXISTS tour_itinerary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id UUID NOT NULL REFERENCES tourpackages(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    location_name TEXT NOT NULL,
    location_type TEXT NOT NULL CHECK (location_type IN ('pickup', 'stop', 'dropoff')),
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    duration_hours INTEGER DEFAULT 0,
    duration_minutes INTEGER DEFAULT 0,
    description TEXT,
    activities TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_tour_itinerary_package_id ON tour_itinerary(package_id);
CREATE INDEX IF NOT EXISTS idx_tour_itinerary_step_order ON tour_itinerary(package_id, step_order);

-- Add trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_tour_itinerary_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tour_itinerary_updated_at
    BEFORE UPDATE ON tour_itinerary
    FOR EACH ROW
    EXECUTE FUNCTION update_tour_itinerary_updated_at();

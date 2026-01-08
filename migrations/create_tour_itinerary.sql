-- Create tour_itinerary table for step-by-step tour details
CREATE TABLE IF NOT EXISTS public.tour_itinerary (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  package_id UUID NOT NULL,
  step_order INTEGER NOT NULL,
  location_name TEXT NOT NULL,
  location_type TEXT NOT NULL CHECK (location_type IN ('pickup', 'stop', 'dropoff')),
  latitude NUMERIC(10, 8) NOT NULL,
  longitude NUMERIC(11, 8) NOT NULL,
  duration_hours INTEGER DEFAULT 0,
  duration_minutes INTEGER DEFAULT 0,
  description TEXT,
  activities TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT tour_itinerary_pkey PRIMARY KEY (id),
  CONSTRAINT tour_itinerary_package_fkey FOREIGN KEY (package_id) REFERENCES public.tourpackages(id) ON DELETE CASCADE
) TABLESPACE pg_default;

CREATE INDEX IF NOT EXISTS idx_tour_itinerary_package ON public.tour_itinerary USING btree (package_id) TABLESPACE pg_default;
CREATE INDEX IF NOT EXISTS idx_tour_itinerary_order ON public.tour_itinerary USING btree (package_id, step_order) TABLESPACE pg_default;

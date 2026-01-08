-- Sample itinerary data for testing
-- Replace 'YOUR_PACKAGE_ID' with an actual package ID from your tourpackages table

-- First, check if you have packages:
-- SELECT id, package_name FROM tourpackages LIMIT 5;

-- Example: Add itinerary for a "Historic Cebu City Tour" package
-- Replace the package_id below with your actual package ID

INSERT INTO tour_itinerary (package_id, step_order, location_name, location_type, latitude, longitude, duration_hours, duration_minutes, description, activities)
VALUES 
  -- Step 1: Starting point
  ('YOUR_PACKAGE_ID', 1, 'Plaza Independencia', 'pickup', 10.2926, 123.9058, 0, 30, 'Starting point of the historic tour', 
   ARRAY['Photo opportunity at the plaza', 'Brief history of Cebu City', 'Meet your tartanilla driver']),
  
  -- Step 2: First stop
  ('YOUR_PACKAGE_ID', 2, 'Fort San Pedro', 'stop', 10.2931, 123.9065, 0, 45, 'Historic Spanish fortress and military defense', 
   ARRAY['Guided tour of the fort', 'Visit the museum', 'Walk along the ramparts', 'Photo session at cannons']),
  
  -- Step 3: Second stop
  ('YOUR_PACKAGE_ID', 3, 'Magellan''s Cross', 'stop', 10.2933, 123.9021, 0, 30, 'Iconic historical landmark from 1521', 
   ARRAY['View the historic cross', 'Learn about Magellan''s arrival', 'Photo opportunity', 'Visit nearby vendors']),
  
  -- Step 4: Third stop
  ('YOUR_PACKAGE_ID', 4, 'Basilica del Santo Niño', 'stop', 10.2934, 123.9019, 0, 45, 'Oldest Roman Catholic church in the Philippines', 
   ARRAY['Church visit and prayer', 'View the Santo Niño image', 'Explore the museum', 'Light candles']),
  
  -- Step 5: Fourth stop
  ('YOUR_PACKAGE_ID', 5, 'Colon Street', 'stop', 10.2945, 123.9010, 0, 30, 'Oldest street in the Philippines', 
   ARRAY['Walk along historic street', 'Visit local shops', 'Try local snacks', 'Photo opportunities']),
  
  -- Step 6: Return
  ('YOUR_PACKAGE_ID', 6, 'Plaza Independencia', 'dropoff', 10.2926, 123.9058, 0, 15, 'Return to starting point', 
   ARRAY['Drop-off at plaza', 'Thank your driver', 'Share your experience']);

-- To use this script:
-- 1. Find your package ID: SELECT id, package_name FROM tourpackages;
-- 2. Replace 'YOUR_PACKAGE_ID' with the actual UUID
-- 3. Run this script in your database

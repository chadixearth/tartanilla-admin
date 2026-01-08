-- Add verification fields to the bookings table
-- This migration adds support for tour completion verification

-- Add verification photo URL field
ALTER TABLE bookings 
ADD COLUMN IF NOT EXISTS verification_photo_url TEXT;

-- Add verification status field
-- Status can be: 'pending', 'verified', 'reported'
ALTER TABLE bookings 
ADD COLUMN IF NOT EXISTS verification_status VARCHAR(50) DEFAULT 'pending';

-- Add timestamp for when verification photo was uploaded
ALTER TABLE bookings 
ADD COLUMN IF NOT EXISTS verification_uploaded_at TIMESTAMP;

-- Add field to track if tourist reported the photo
ALTER TABLE bookings 
ADD COLUMN IF NOT EXISTS tourist_reported BOOLEAN DEFAULT FALSE;

-- Add field for report reason
ALTER TABLE bookings 
ADD COLUMN IF NOT EXISTS report_reason TEXT;

-- Add timestamp for when the report was made
ALTER TABLE bookings 
ADD COLUMN IF NOT EXISTS report_timestamp TIMESTAMP;

-- Add field to track if verification is required (for backward compatibility)
ALTER TABLE bookings 
ADD COLUMN IF NOT EXISTS verification_required BOOLEAN DEFAULT TRUE;

-- Create index for faster queries on verification status
CREATE INDEX IF NOT EXISTS idx_bookings_verification_status 
ON bookings(verification_status);

-- Create index for reported bookings
CREATE INDEX IF NOT EXISTS idx_bookings_tourist_reported 
ON bookings(tourist_reported);

-- Add comment to table
COMMENT ON COLUMN bookings.verification_photo_url IS 'URL of the photo uploaded by driver to verify tour completion';
COMMENT ON COLUMN bookings.verification_status IS 'Status of verification: pending, verified, reported';
COMMENT ON COLUMN bookings.verification_uploaded_at IS 'Timestamp when driver uploaded verification photo';
COMMENT ON COLUMN bookings.tourist_reported IS 'Flag indicating if tourist reported the verification photo as fraudulent';
COMMENT ON COLUMN bookings.report_reason IS 'Reason provided by tourist for reporting the photo';
COMMENT ON COLUMN bookings.report_timestamp IS 'Timestamp when tourist reported the photo';
COMMENT ON COLUMN bookings.verification_required IS 'Whether verification is required for this booking';

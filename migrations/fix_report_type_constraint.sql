-- Drop the old constraint
ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_report_type_check;

-- Add new constraint with goods_services_violation included
ALTER TABLE reports ADD CONSTRAINT reports_report_type_check 
CHECK (report_type IN (
    'driver_cancellation',
    'tourist_complaint', 
    'driver_complaint',
    'system_issue',
    'verification_fraud',
    'trip_issue',
    'goods_services_violation'
));

-- Add metadata column if not exists
ALTER TABLE reports ADD COLUMN IF NOT EXISTS metadata JSONB;
CREATE INDEX IF NOT EXISTS idx_reports_metadata ON reports USING GIN (metadata);

-- Add columns to goods_services_profiles
ALTER TABLE goods_services_profiles ADD COLUMN IF NOT EXISTS removed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE goods_services_profiles ADD COLUMN IF NOT EXISTS removed_reason TEXT;

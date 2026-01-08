-- Add metadata column for storing post_id and report details
ALTER TABLE reports ADD COLUMN IF NOT EXISTS metadata JSONB;

-- Create index for metadata queries
CREATE INDEX IF NOT EXISTS idx_reports_metadata ON reports USING GIN (metadata);

-- Add removed columns to goods_services_profiles
ALTER TABLE goods_services_profiles ADD COLUMN IF NOT EXISTS removed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE goods_services_profiles ADD COLUMN IF NOT EXISTS removed_reason TEXT;

-- Note: report_type and decision columns already exist, no changes needed
-- The new report type 'goods_services_violation' will be inserted as text (no enum constraint visible)

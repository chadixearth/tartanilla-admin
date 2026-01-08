-- Add goods_services_violation to report_type enum
-- This allows reporting of goods & services posts that violate community guidelines

-- First, check if the reports table exists
DO $$ 
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'reports') THEN
        -- Add the new report type to the enum if it doesn't exist
        BEGIN
            ALTER TYPE report_type ADD VALUE IF NOT EXISTS 'goods_services_violation';
        EXCEPTION
            WHEN duplicate_object THEN
                -- Type already exists, do nothing
                NULL;
        END;
        
        -- Add metadata column if it doesn't exist (for storing post_id and other details)
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'reports' AND column_name = 'metadata'
        ) THEN
            ALTER TABLE reports ADD COLUMN metadata JSONB;
            CREATE INDEX IF NOT EXISTS idx_reports_metadata ON reports USING GIN (metadata);
        END IF;
        
        -- Add decision column if it doesn't exist (for admin decisions)
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'reports' AND column_name = 'decision'
        ) THEN
            ALTER TABLE reports ADD COLUMN decision TEXT;
        END IF;
        
        RAISE NOTICE 'Successfully updated reports table for goods & services reporting';
    ELSE
        RAISE NOTICE 'Reports table does not exist. Please run create_reports_table.py first.';
    END IF;
END $$;

-- Add removed_at and removed_reason columns to goods_services_profiles if they don't exist
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'goods_services_profiles') THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'goods_services_profiles' AND column_name = 'removed_at'
        ) THEN
            ALTER TABLE goods_services_profiles ADD COLUMN removed_at TIMESTAMP WITH TIME ZONE;
        END IF;
        
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'goods_services_profiles' AND column_name = 'removed_reason'
        ) THEN
            ALTER TABLE goods_services_profiles ADD COLUMN removed_reason TEXT;
        END IF;
        
        RAISE NOTICE 'Successfully updated goods_services_profiles table';
    END IF;
END $$;

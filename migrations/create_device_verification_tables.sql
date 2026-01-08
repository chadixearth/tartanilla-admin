-- Create device verification tables

-- Table for trusted devices
CREATE TABLE IF NOT EXISTS trusted_devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    device_fingerprint VARCHAR(255) NOT NULL,
    device_info TEXT,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, device_fingerprint)
);

-- Table for device verification requests
CREATE TABLE IF NOT EXISTS device_verification_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    device_fingerprint VARCHAR(255) NOT NULL,
    verification_code VARCHAR(6) NOT NULL,
    device_info TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_verified BOOLEAN DEFAULT FALSE,
    verified_at TIMESTAMP WITH TIME ZONE
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_trusted_devices_user_id ON trusted_devices(user_id);
CREATE INDEX IF NOT EXISTS idx_trusted_devices_fingerprint ON trusted_devices(device_fingerprint);
CREATE INDEX IF NOT EXISTS idx_device_verification_user_id ON device_verification_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_device_verification_code ON device_verification_requests(verification_code);

-- Enable RLS
ALTER TABLE trusted_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_verification_requests ENABLE ROW LEVEL SECURITY;

-- RLS Policies for trusted_devices
CREATE POLICY "Users can view their own trusted devices"
    ON trusted_devices FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage all trusted devices"
    ON trusted_devices FOR ALL
    USING (auth.role() = 'service_role');

-- RLS Policies for device_verification_requests
CREATE POLICY "Users can view their own verification requests"
    ON device_verification_requests FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage all verification requests"
    ON device_verification_requests FOR ALL
    USING (auth.role() = 'service_role');

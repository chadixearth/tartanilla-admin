-- Add address column to users table
ALTER TABLE public.users 
ADD COLUMN IF NOT EXISTS address text NULL;

# Deployment Guide - Tartanilla Tourism Management System

## Deploy to Render (Recommended - Free Tier Available)

### Prerequisites
1. GitHub account
2. Render account (free at render.com)

### Step 1: Prepare Repository
1. Push your code to GitHub repository
2. Ensure all deployment files are included:
   - `render.yaml`
   - `requirements_production.txt`
   - `build.sh`
   - `Procfile`

### Step 2: Deploy on Render
1. Go to [render.com](https://render.com) and sign up/login
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Configure deployment:
   - **Name**: tartanilla-admin
   - **Environment**: Python 3
   - **Build Command**: `./build.sh`
   - **Start Command**: `gunicorn tartanilla_admin.wsgi:application`
   - **Instance Type**: Free

### Step 3: Set Environment Variables
In Render dashboard, add these environment variables (use your actual values):
```
DEBUG=False
SECRET_KEY=[generate-random-key]
SUPABASE_URL=[your-supabase-url]
SUPABASE_ANON_KEY=[your-supabase-anon-key]
SUPABASE_SERVICE_ROLE_KEY=[your-supabase-service-role-key]
PAYMONGO_SECRET_KEY=[your-paymongo-secret-key]
PAYMONGO_PUBLIC_KEY=[your-paymongo-public-key]
PAYMONGO_WEBHOOK_SECRET=[your-paymongo-webhook-secret]
TWILIO_ACCOUNT_SID=[your-twilio-account-sid]
TWILIO_AUTH_TOKEN=[your-twilio-auth-token]
TWILIO_PHONE_NUMBER=[your-twilio-phone-number]
```

### Step 4: Deploy
1. Click "Create Web Service"
2. Wait for deployment to complete (5-10 minutes)
3. Your app will be available at: `https://tartanilla-admin.onrender.com`

---

## Post-Deployment Steps

### 1. Test Deployment
1. Visit your deployed URL
2. Test admin login at `/admin/`
3. Test API endpoints at `/api/`

### 2. Create Admin User
Use Render web console to run:
```bash
python manage.py createsuperuser
```

---

## Free Tier Limitations

### Render Free Tier:
- 750 hours/month
- Sleeps after 15 minutes of inactivity
- 512MB RAM

Your app will be live at: `https://your-app-name.onrender.com`
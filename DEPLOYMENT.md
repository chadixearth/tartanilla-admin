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
In Render dashboard, add these environment variables:
```
DEBUG=False
SECRET_KEY=[generate-random-key]
SUPABASE_URL=https://sncruycikvfnkrmmbjxr.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuY3J1eWNpa3ZmbmtybW1ianhyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTEwMTQ1NDIsImV4cCI6MjA2NjU5MDU0Mn0.NOJVi5idcC3hIZVl5W6Spjs-DBH0_mDINc0Jr0H5v7s
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuY3J1eWNpa3ZmbmtybW1ianhyIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MTAxNDU0MiwiZXhwIjoyMDY2NTkwNTQyfQ.GLabXRi042t6xtrwtkgdcOJOPRtBUgI5dEmMpS8ScZs
PAYMONGO_SECRET_KEY=sk_test_yPB81EbFLpqtYiCfzVzXhqaB
PAYMONGO_PUBLIC_KEY=pk_test_X2mCC9cJCwXerMPNCmT4vxQt
PAYMONGO_WEBHOOK_SECRET=whsk_UPpezYNUdHA2kotXBE3bL4qK
TWILIO_ACCOUNT_SID=AC60f1008e3324889b0ffce96c5a359306
TWILIO_AUTH_TOKEN=2eff9378cc059399669df4027fd6c8ad
TWILIO_PHONE_NUMBER=+19124522183
```

### Step 4: Deploy
1. Click "Create Web Service"
2. Wait for deployment to complete (5-10 minutes)
3. Your app will be available at: `https://tartanilla-admin.onrender.com`

---

## Alternative: Deploy to Railway (Free Tier)

### Step 1: Setup Railway
1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub
3. Click "New Project" → "Deploy from GitHub repo"

### Step 2: Configure
1. Select your repository
2. Railway will auto-detect Django
3. Add environment variables (same as above)
4. Deploy automatically starts

---

## Alternative: Deploy to Heroku (Paid)

### Step 1: Install Heroku CLI
```bash
# Install Heroku CLI
npm install -g heroku
```

### Step 2: Deploy
```bash
# Login to Heroku
heroku login

# Create app
heroku create tartanilla-admin

# Set environment variables
heroku config:set DEBUG=False
heroku config:set SECRET_KEY=your-secret-key
# ... add all other env vars

# Deploy
git push heroku main
```

---

## Post-Deployment Steps

### 1. Update CORS Settings
Add your deployment URL to CORS_ALLOWED_ORIGINS in settings.py:
```python
CORS_ALLOWED_ORIGINS = [
    "https://your-app-name.onrender.com",
]
```

### 2. Create Admin User
```bash
# For Render (use web console)
python manage.py createsuperuser

# For Heroku
heroku run python manage.py createsuperuser
```

### 3. Test Deployment
1. Visit your deployed URL
2. Test admin login at `/admin/`
3. Test API endpoints at `/api/`

---

## Troubleshooting

### Common Issues:
1. **Static files not loading**: Ensure WhiteNoise is configured
2. **Environment variables**: Double-check all required vars are set
3. **Build failures**: Check build logs for missing dependencies

### Logs:
- **Render**: View logs in dashboard
- **Railway**: Check deployment logs
- **Heroku**: `heroku logs --tail`

---

## Free Tier Limitations

### Render Free Tier:
- 750 hours/month
- Sleeps after 15 minutes of inactivity
- 512MB RAM

### Railway Free Tier:
- $5 credit/month
- No sleep mode
- Better performance

### Recommendation:
Start with **Render** for completely free hosting, upgrade to Railway or paid Heroku for production use.
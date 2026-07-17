# Tartanilla Admin

Django REST API admin panel for the **Tartanilla Tourism Management System** — a Philippine-style tricycle (tartanilla) tourism ecosystem connecting tourists, drivers, and operators across routes, bookings, payments, chat support, and real-time operations.

[![Django](https://img.shields.io/badge/Django-5.2-092E20?logo=django)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16-A30000?logo=django)](https://www.django-rest-framework.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-4169E1?logo=postgresql)](https://supabase.com/)
[![JWT](https://img.shields.io/badge/Auth-JWT-000000?logo=jsonwebtokens)](https://jwt.io/)
[![WebSockets](https://img.shields.io/badge/Real--time-WebSockets-010101?logo=socket.io)](https://websockets.readthedocs.io/)
[![Twilio](https://img.shields.io/badge/SMS-Twilio-F22F46?logo=twilio)](https://www.twilio.com/)
[![PayMongo](https://img.shields.io/badge/Payments-PayMongo-7B3FE4)](https://paymongo.com/)
[![Render](https://img.shields.io/badge/Deploy-Render-46E3B7?logo=render)](https://render.com/)

---

## Domain Context

A **tartanilla** is a colorful open-air tricycle used for short-distance tourism in the Philippines (most famously in Vigan, Ilocos Sur). This system digitizes the entire tourism workflow:

- **Tourists** book tour packages or hail rides via a mobile app
- **Drivers** accept bookings, manage schedules, and receive earnings
- **Operators** own and manage tartanilla carriages
- **Admins** (this panel) oversee routes, users, drivers, tours, finances, disputes, and compliance

This admin panel is the back-office interface and REST API backend consumed by the mobile front-end.

---

## Features

| Module | Description |
|--------|-------------|
| **Route Management** | Set road restrictions, define allowed roads, monitor compliance |
| **User Management** | Approve/reject owner & driver applications, suspend accounts, manage eligibility |
| **Tour Packages** | Create, update, deactivate packages; handle custom tour requests |
| **Driver Assignment** | Manage driver-carriage assignments and scheduling |
| **Financial Dashboard** | Monitor bookings, revenues, driver/owner earnings |
| **Booking Engine** | Tour bookings, ride-hailing, payment processing (PayMongo) |
| **Complaints & Reports** | Handle disputes from tourists, owners, and drivers |
| **Audit Logs** | Track all system activities and admin actions |
| **Chat Support** | Real-time customer support via WebSockets |
| **Notifications** | Push notifications, SMS alerts (Twilio), breakeven alerts |
| **Map Services** | GPS tracking, routing, terminals/stops/drop-off points |
| **Goods & Services** | Marketplace-style posts, profile, reviews, violation reports |
| **Analytics** | System-wide metrics, reports, and data exports |
| **Account Deletion** | User request workflow with scheduled processing |
| **Payment Refunds** | Process refunds and manage payment disputes |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              Mobile App (Expo/RN)            │
└──────────────────┬──────────────────────────┘
                   │ HTTPS / WebSockets
┌──────────────────▼──────────────────────────┐
│        Tartanilla Admin (Django DRF)         │
│  ┌─────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ REST API │ │ WebSocket│ │ Admin Panel   │ │
│  │ (DRF)    │ │ Channels │ │ (Django Admin)│ │
│  └────┬─────┘ └────┬─────┘ └──────────────┘ │
└───────┼─────────────┼───────────────────────┘
        │             │
┌───────▼─────────────▼───────────────────────┐
│           Supabase (PostgreSQL + Storage)     │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Database  │ │ Auth     │ │ File Storage │ │
│  └──────────┘ └──────────┘ └──────────────┘ │
└─────────────────────────────────────────────┘
        │
┌───────▼─────────────────────────────────────┐
│  External Services                           │
│  PayMongo (payments) · Twilio (SMS)         │
│  OpenRouteService (routing) · ngrok (tunnel) │
└─────────────────────────────────────────────┘
```

### Key Design Decisions

- **Supabase as database backend** — Django uses a dummy database backend; all CRUD goes through the Supabase Python client (`supabase-py`), not Django ORM. This means no Django migrations for production data.
- **Service role key** — Backend uses Supabase's service role key (bypasses RLS) for admin operations; user auth handled via Supabase Auth + JWT.
- **Session-based auth for admin** — Admin panel uses Django session auth; mobile API uses Supabase JWT tokens.
- **No traditional Django models** — The `models.py` files in each app define Supabase table schemas as documentation; actual tables live in Supabase.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11, Django 5.2, Django REST Framework 3.16 |
| **Database** | PostgreSQL (via Supabase) |
| **Auth** | Supabase Auth (JWT) + Django Session Auth |
| **Real-time** | WebSockets via `websockets` library |
| **File Storage** | Supabase Storage (buckets: profile-photos, tourpackage-photos, booking-verifications, goods-storage, tartanilla-media) |
| **Payments** | PayMongo API (GCash, GrabPay, Maya, card) |
| **SMS** | Twilio API |
| **Maps** | OpenRouteService API |
| **Deployment** | Render (Web Service + cron) |
| **Static Files** | WhiteNoise |

---

## Project Structure

```
tartanilla_admin/
├── manage.py
├── requirements.txt               # Dev dependencies
├── requirements_production.txt    # Production (+ gunicorn, whitenoise, reportlab)
├── requirements_clean.txt
├── Procfile                       # Render: gunicorn entrypoint
├── render.yaml                    # Render infrastructure-as-code
├── build.sh                       # Render build script
├── runtime.txt                    # Python 3.11.0
├── .env.example                   # Environment variable template
├── .gitignore
├── README.md
├── DEPLOYMENT.md
│
├── tartanilla_admin/              # Django project config
│   ├── settings.py                # Dev settings (Supabase client, CORS, DRF)
│   ├── production_settings.py     # Production overrides
│   ├── urls.py                    # Root URL routing
│   ├── wsgi.py / asgi.py
│   ├── supabase.py                # Supabase client factory + storage utils
│   └── accounts/                  # Supabase auth config
│
├── api/                           # REST API (DRF viewsets + function views)
│   ├── urls.py                    # All API route definitions
│   ├── views.py / serializers.py
│   ├── authentication.py          # Login, register, profile, password mgmt
│   ├── booking.py / ride_hailing.py
│   ├── earnings.py / breakeven.py
│   ├── payment.py / refunds.py / payment_completion.py
│   ├── notifications.py / realtime_notifications.py
│   ├── reviews.py / analytics.py / reports.py
│   ├── tartanilla.py / driver_schedule.py
│   ├── map.py / routing.py / location.py
│   ├── user_management.py / user_list.py / sync_user.py
│   ├── account_deletion.py / verification.py / device_verification.py
│   ├── admin_approval.py / pending_registrations.py
│   ├── goods_services_post.py / goods_services_reports.py
│   ├── health.py / health_check.py
│   └── ... (60+ endpoint modules)
│
├── core/                          # Shared utilities
│   ├── jwt_auth.py                # JWT validation middleware
│   ├── validators.py              # Input sanitization
│   ├── email_utils.py / sms_utils.py
│   ├── cache_utils.py / api_utils.py / view_utils.py
│   ├── auth_decorators.py
│   ├── security_middleware.py / mobile_security.py
│   ├── connection_manager.py / enhanced_connection_manager.py
│   ├── error_handlers.py / middleware.py
│   └── startup.py / startup_health_monitor.py
│
├── accounts/                      # User accounts app + login/templates
├── chat/                          # Chat WebSocket handling
├── chatsupport/                   # Customer support chat
├── tourpackage/                   # Tour package management
├── routemanagement/               # Route definitions & restrictions
├── earningsAndshares/             # Earnings & revenue share
├── auditlogs/                     # System audit trail
├── tartanillacarriages/           # Carriage/fleet management
├── announcements/                 # System announcements
├── reports/                       # PDF/etc. report generation
├── migrations/                    # Schema documentation stubs
│
├── static/                        # Static assets (CSS/JS)
├── templates/                     # Django templates
├── sql/                           # Raw SQL scripts
└── scripts/                       # Standalone utilities
    └── process_scheduled_deletions.py
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DEBUG` | No | Set `False` for production (default: `True`) |
| `SECRET_KEY` | Yes | Django secret key (auto-generated on Render) |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | Supabase anonymous/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Supabase service role key (bypasses RLS) |
| `PAYMONGO_SECRET_KEY` | No | PayMongo API secret key |
| `PAYMONGO_PUBLIC_KEY` | No | PayMongo API public key |
| `PAYMONGO_WEBHOOK_SECRET` | No | PayMongo webhook signing secret |
| `TWILIO_ACCOUNT_SID` | No | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | No | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | No | Twilio SMS sender number |

Copy `.env.example` to `.env` and fill in values for local development.

---

## Setup

### Prerequisites

- Python 3.11+
- A Supabase project (free tier works)
- Git

### 1. Clone & Enter

```bash
git clone https://github.com/your-org/tartanilla-admin.git
cd tartanilla_admin
```

### 2. Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Environment

```bash
cp .env.example .env
```

Edit `.env` with your Supabase credentials and optional PayMongo/Twilio keys.

### 5. Run

```bash
python manage.py runserver
```

- Admin panel: `http://127.0.0.1:8000/admin/`
- API root: `http://127.0.0.1:8000/api/`
- Health check: `http://127.0.0.1:8000/health/`

> **Note**: This project uses Supabase as its database — there is no local PostgreSQL required. Django's database backend is set to `django.db.backends.dummy`. All data operations go through the Supabase Python client. The `migrate` and `makemigrations` commands are not used for production data.

---

## API Overview

Base path: `/api/`

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health/` | Full health check |
| GET | `/api/ping/` | Ultra-fast ping |
| GET | `/api/quick/` | Minimal health check (no DRF overhead) |
| GET | `/health/` | Root health check |

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register/` | Register new user |
| POST | `/api/auth/login/` | User login |
| POST | `/api/auth/admin-login/` | Admin login |
| POST | `/api/auth/logout/` | Logout |
| POST | `/api/auth/refresh/` | Refresh JWT token |
| GET | `/api/auth/verify-token/` | Verify token validity |
| GET | `/api/auth/profile/` | Get user profile |
| GET | `/api/auth/user/{user_id}/` | Get profile by ID |
| PUT | `/api/auth/profile/update/` | Update profile |
| POST | `/api/auth/profile/photo/` | Upload profile photo |
| POST | `/api/auth/change-password/` | Change password |
| POST | `/api/auth/resend-confirmation/` | Resend confirmation email |
| POST | `/api/auth/forgot-password/` | Request password reset |
| POST | `/api/auth/verify-reset-code/` | Verify reset code |
| POST | `/api/auth/reset-password-confirm/` | Confirm password reset |
| POST | `/api/auth/switch-role/` | Switch user role |
| GET | `/api/auth/available-roles/` | Get available roles |
| GET | `/api/auth/check-suspension/` | Check account suspension |

### Verification

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/send-verification/` | Send verification code |
| POST | `/api/auth/verify-code/` | Verify code |
| POST | `/api/auth/resend-verification/` | Resend verification code |
| POST | `/api/auth/check-device/` | Device trust check |
| POST | `/api/auth/verify-device/` | Verify trusted device |

### User Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/auth/users/` | List all users |
| POST | `/api/auth/sync-user/` | Sync user from Supabase |
| POST | `/api/admin/users/suspend/` | Suspend user |
| POST | `/api/admin/users/unsuspend/` | Unsuspend user |
| GET | `/api/admin/users/suspension-status/` | Check suspension status |
| GET | `/api/admin/users/suspended/` | List suspended users |

### Admin Approvals

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/auth/pending/` | List pending registrations |
| POST | `/api/auth/pending/approve/` | Approve registration |
| POST | `/api/auth/pending/reject/` | Reject registration |
| GET | `/api/admin/applications/` | List pending applications |
| POST | `/api/admin/applications/approve/` | Approve application |
| POST | `/api/admin/applications/reject/` | Reject application |
| POST | `/api/admin/applications/resend-credentials/` | Resend credentials |

### Tours & Bookings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/tourpackage/` | List/create tour packages |
| GET/PUT/DELETE | `/api/tourpackage/{id}/` | Retrieve/update/delete package |
| GET/POST | `/api/tour-booking/` | List/create tour bookings |
| GET/POST | `/api/custom-tour-requests/` | Custom tour requests |
| GET/POST | `/api/special-event-requests/` | Special event requests |

### Ride-Hailing

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/ride-hailing/` | List/create ride-hailing requests |

### Tartanilla Carriages

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/tartanilla-carriages/` | List/create carriages |

### Earnings & Breakeven

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/earnings/` | Earnings management |
| GET/POST | `/api/breakeven/` | Breakeven analysis |
| GET/POST | `/api/driver-schedule/` | Driver schedule management |
| GET/POST | `/api/driver-carriage-helper/` | Driver-carriage assignment helpers |
| GET/POST | `/api/quick-carriage-assign/` | Quick carriage assignment |

### Payments & Refunds

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/payments/` | Payment processing |
| POST | `/api/payment/complete/` | Complete payment |
| GET/POST | `/api/refunds/` | Refund management |

### Map & Location

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/map/data/` | Get all map data |
| GET | `/api/map/terminals/` | List terminals |
| GET | `/api/map/stops/` | List stops |
| GET | `/api/map/dropoff-points/` | List drop-off points |
| POST | `/api/map/points/` | Add map point |
| PUT | `/api/map/points/{id}/` | Update map point |
| DELETE | `/api/map/points/{id}/delete/` | Delete map point |
| POST | `/api/map/roads/` | Add road highlight |
| GET | `/api/map/road-highlights/` | List road highlights |
| GET | `/api/map/routes/` | List routes |
| GET | `/api/map/route/?start_lat=&start_lng=&end_lat=&end_lng=` | Get route directions |
| POST | `/api/location/update/` | Update driver location |
| GET | `/api/location/drivers/` | Get driver locations |

### Notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/notifications/` | List notifications |
| POST | `/api/notifications/mark-read/` | Mark notification as read |
| POST | `/api/notifications/store-token/` | Store push token |
| GET | `/api/notifications/stream/` | Notification stream (SSE) |
| POST | `/api/notifications/push/` | Send push notification |
| GET | `/api/notifications/breakeven/` | Breakeven alerts |

### Reviews & Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/reviews/` | Reviews CRUD |
| GET/POST | `/api/analytics/` | System analytics |
| GET/POST | `/api/reports/` | Report generation |

### Audit & Security

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/auditlogs/` | Audit log entries |
| GET | `/api/csrf-token/` | Get CSRF token |
| POST | `/api/validate-input/` | Validate/sanitize input |

### Goods & Services

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/goods-services-profiles/` | Goods & services profiles |
| GET/POST | `/api/goods-services-posts/` | Posts (alias) |
| GET/POST | `/api/goods-services-reports/` | Violation reports |

### Photo Uploads

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload/profile-photo/` | Upload profile photo |
| POST | `/api/upload/tourpackage-photo/` | Upload tour package photo |
| POST | `/api/upload/multiple-photos/` | Upload multiple photos |
| POST | `/api/upload/goods-storage/` | Upload goods storage media |
| POST | `/api/upload/tartanilla-media/` | Upload tartanilla media |
| POST | `/api/upload/map-point-photo/` | Upload map point photo |
| PUT | `/api/map/points/{id}/image/` | Update map point image |

### Account Deletion

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/request-deletion/` | Request account deletion |
| POST | `/api/auth/cancel-deletion/` | Cancel deletion |
| POST | `/api/auth/cancel-deletion-and-login/` | Cancel deletion & login |
| GET | `/api/auth/deletion-status/` | Check deletion status |
| GET | `/api/auth/deletion-requests/` | List deletion requests |
| POST | `/api/auth/process-scheduled-deletions/` | Process scheduled deletions |

---

## Testing

```bash
# Run all tests
python manage.py test

# Run tests for specific app
python manage.py test api

# Run with coverage
pip install coverage
coverage run manage.py test
coverage report
```

---

## Deployment

### Render (Recommended)

This project includes Render infrastructure-as-code:

- **`render.yaml`** — Blueprint for auto-deploy
- **`Procfile`** — `gunicorn tartanilla_admin.wsgi:application`
- **`build.sh`** — `pip install` + `collectstatic`
- **`runtime.txt`** — Python 3.11.0
- **`requirements_production.txt`** — Production deps (adds gunicorn, whitenoise, reportlab)

**Steps:**

1. Push to GitHub
2. On [render.com](https://render.com), click **New → Web Service**
3. Connect your repo
4. Set build command: `./build.sh`
5. Set start command: `gunicorn tartanilla_admin.wsgi:application`
6. Add environment variables (see table above)
7. Deploy

App will be live at `https://tartanilla-admin.onrender.com`.

See `DEPLOYMENT.md` for detailed instructions, free-tier limitations, and post-deployment steps.

### Production Considerations

- Enable `production_settings.py` by setting `DJANGO_SETTINGS_MODULE=tartanilla_admin.production_settings`
- Set `DEBUG=False` and provide a strong `SECRET_KEY`
- Configure `ALLOWED_HOSTS` for your domain
- Review CORS origins in production settings
- WhiteNoise serves static files in production (no need for CDN)

---

## Security

| Measure | Implementation |
|---------|---------------|
| **Audit Logging** | Every admin action recorded in `auditlogs` table |
| **Role-Based Access** | Supabase user roles (admin, driver, tourist, owner) |
| **Input Validation** | Sanitization on all API inputs (`core/validators.py`) |
| **CSRF Protection** | Django CSRF middleware + custom cookie/token |
| **JWT Authentication** | Supabase Auth JWT for mobile API access |
| **Session Security** | Signed cookies, `HttpOnly`, `SameSite=Lax`, 7-day expiry |
| **HTTPS** | Redirect enabled in production via `SECURE_SSL_REDIRECT` |
| **HSTS** | 1-year HSTS policy in production |
| **Rate Limiting** | DRF throttling: 100 req/min (anon), 1000 req/min (auth) |
| **XSS Protection** | `SECURE_BROWSER_XSS_FILTER` enabled |
| **Content Security** | `X-Frame-Options: DENY` to prevent clickjacking |
| **Payment Security** | PayMongo webhook signature verification |
| **Data Sanitization** | Bleach/defusedxml for HTML/safe content |
| **Session in Cookies** | No server-side session store; signed cookies only |

---

## Development Notes

- **Database**: Supabase (PostgreSQL) — no local DB needed. Django ORM `migrate` is not used for production tables.
- **Authentication**: Dual system — Django sessions for admin web; Supabase Auth JWT for mobile app.
- **CORS**: Wide open in development (`CORS_ALLOW_ALL_ORIGINS=True`); locked to specific origins in production.
- **Real-time**: WebSockets via `websockets` library for live notifications and chat.
- **File Storage**: Supabase Storage buckets — configure cloud storage for production.
- **Session Storage**: Cookies-based (`signed_cookies`), no database dependency.
- **Error Handling**: Custom middleware for JSON error formatting, response limiting, and connection health.

---

## Contributing

1. Create a feature branch from `develop`
2. Make changes with appropriate tests
3. Submit a pull request for review
4. Ensure all tests pass before merging

---

## Support

For technical support or questions, contact the development team or refer to project documentation.

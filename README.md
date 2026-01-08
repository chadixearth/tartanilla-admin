# Tartanilla Tourism Management System - Admin Web Application

A Django REST API web application for administrators to manage the Tartanilla tourism ecosystem, including route management, user accounts, tour packages, and system oversight.

## Project Overview

This web application serves as the **Admin Panel** for the Tartanilla Tourism Management System, providing administrators with comprehensive tools to:

### Admin Features

- **Route Management**: Set road restrictions and allowed roads
- **User Account Management**: Handle account suspensions, driver eligibility, and application approvals
- **Tour Package Management**: Create, update, and deactivate tour packages
- **Driver Assignment**: Manage driver assignments and scheduling
- **Financial Dashboard**: Monitor system-wide financial metrics
- **User Complaints & Reports**: Handle complaints from tourists, owners, and drivers
- **Audit Logs**: Track system activities and changes
- **Booking History**: View driver and tourist booking records
- **Chat Support**: Provide customer support
- **Notifications**: Manage user complaints and reports

## Setup Instructions

### Prerequisites

- Python 3.8 or higher
- PostgreSQL database/sqllite
- Git

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd CapstoneWeb
```

### Step 2: Create Virtual Environment

```bash
python -m venv venv
```

### Step 3: Activate Virtual Environment

```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Environment Configuration

Create a `.env` file in the root directory:

```bash
# Copy example environment file
cp .env.example .env
```

Update the `.env` file with your database credentials and settings.

### Step 6: Create Django Project

```bash
django-admin startproject tartanilla_admin
cd tartanilla_admin
```

### Step 8: Database Setup

```bash
python manage.py makemigrations
python manage.py migrate
```

### Step 9: Create Admin Superuser

```bash
python manage.py createsuperuser
```

### Step 10: Load Initial Data (Optional)

```bash
python manage.py loaddata fixtures/initial_data.json
```

### Step 11: Run Development Server

```bash
python manage.py runserver
```

The admin panel will be available at `http://127.0.0.1:8000/admin/`
API endpoints will be available at `http://127.0.0.1:8000/api/`

## Project Structure

```
CapstoneWeb/
├── requirements.txt
├── .gitignore
├── .env.example
├── README.md
├── venv/
└── tartanilla_admin/
    ├── manage.py
    ├── tartanilla_admin/
    │   ├── settings.py
    │   ├── urls.py
    │   └── wsgi.py
    ├── app1/
    ├── app2/
    ├── app3/
    ├── static/
    ├── media/
    └── templates/
```

## Key Admin Functionalities

### 1. Route Management

- Set road restrictions for Tartanilla operations
- Define allowed roads and routes
- Monitor real-time route compliance

### 2. User Account Management

- Approve/disapprove owner and driver applications
- Set account longevity and suspension periods
- Manage driver eligibility requirements

### 3. Tour Package Management

- Create new tour packages
- Update existing package details
- Deactivate packages when needed

### 4. Financial Oversight

- View system-wide financial dashboard
- Monitor booking revenues
- Track driver and owner earnings

### 5. Complaint Management

- Handle user complaints from all user types
- Generate reports on system issues
- Maintain audit logs for accountability

## API Endpoints

### Authentication

- `POST /api/auth/login/` - Admin login
- `POST /api/auth/logout/` - Admin logout

### User Management

- `GET /api/users/` - List all users
- `POST /api/users/approve/` - Approve user applications
- `PUT /api/users/{id}/suspend/` - Suspend user accounts

### Route Management

- `GET /api/routes/` - List all routes
- `POST /api/routes/restrictions/` - Set road restrictions
- `PUT /api/routes/{id}/` - Update route information

### Tour Management

- `GET /api/tours/` - List tour packages
- `POST /api/tours/` - Create tour package
- `PUT /api/tours/{id}/` - Update tour package
- `DELETE /api/tours/{id}/` - Deactivate tour package

## Development Notes

- **Database**: Uses PostgreSQL for production, SQLite for development
- **Authentication**: JWT-based authentication for API access
- **Frontend**: Admin panel built with Django templates and Bootstrap
- **API**: RESTful API using Django REST Framework
- **Real-time Features**: WebSocket integration for live updates
- **File Storage**: Media files stored locally (configure cloud storage for production)

## Security Considerations

- All admin actions are logged in audit trails
- Role-based access control implemented
- Input validation and sanitization on all forms
- CSRF protection enabled
- Secure password requirements enforced

## Contributing

1. Create feature branch from `develop`
2. Make changes with appropriate tests
3. Submit pull request for review
4. Ensure all tests pass before merging

## Support

For technical support or questions about the admin panel, contact the development team or refer to the project documentation.

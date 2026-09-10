# Teacher Marketplace Platform

A production-ready backend for a teacher marketplace (similar to UrbanPro), built with
Django 5, Django REST Framework, PostgreSQL, and JWT authentication.

**Students search for teachers for free. Teachers purchase tokens to unlock student
contact details and may purchase premium membership. Students never pay.**

> **Phase 1 scope**: This repository currently contains only the project foundation -
> authentication, user management, and basic Student/Teacher profile CRUD. Wallet,
> token purchases, payments, lead matching, and notifications are NOT implemented yet
> and belong to later phases.

---

## Tech Stack

- **Framework**: Django 5.0
- **API**: Django REST Framework
- **Database**: PostgreSQL
- **Auth**: JWT (djangorestframework-simplejwt)
- **API Docs**: drf-spectacular (Swagger / Redoc)
- **Filtering**: django-filter
- **Images**: Pillow
- **Config**: python-decouple (.env-based)

---

## Project Structure

teacher_marketplace/
├── config/ # Project configuration
│ ├── settings/
│ │ ├── base.py # Shared settings
│ │ ├── development.py # Local dev overrides
│ │ ├── production.py # Production overrides
│ │ └── logging.py # Logging configuration
│ ├── urls.py # Root URL routing
│ ├── wsgi.py
│ └── asgi.py
├── apps/
│ ├── common/ # Abstract base models (UUID, timestamps, soft-delete, audit)
│ ├── core/ # Custom exceptions, exception handler, middleware, API responses
│ ├── utils/ # Reusable validators (email, mobile, password strength)
│ ├── accounts/ # Custom User model + authentication APIs
│ ├── students/ # Student profile model + APIs
│ └── teachers/ # Teacher profile model + APIs
├── media/ # User-uploaded files (gitignored)
├── static/ # Static assets
├── logs/ # Application logs (gitignored)
├── manage.py
├── requirements.txt
├── .env.example
└── .gitignore

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
- pip / virtualenv

---

## Setup Instructions

### 1. Clone the repository and create a virtual environment

```bash
git clone <repository-url>
cd teacher_marketplace
python -m venv venv
source venv/bin/activate      # On Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:
- `SECRET_KEY` — generate one with:
```bash
  python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```
- `DB_NAME`, `DB_USER`, `DB_PASSWORD` — matching the PostgreSQL setup below.

### 4. Create the PostgreSQL database

```bash
psql -U postgres
```

```sql
CREATE DATABASE teacher_marketplace_db;
CREATE USER teacher_marketplace_user WITH PASSWORD 'change_this_password';
ALTER ROLE teacher_marketplace_user SET client_encoding TO 'utf8';
ALTER ROLE teacher_marketplace_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE teacher_marketplace_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE teacher_marketplace_db TO teacher_marketplace_user;
```

### 5. Run migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Create a superuser (SuperAdmin account)

```bash
python manage.py createsuperuser
```

You'll be prompted for email, mobile, first name, last name, and password
(no `username` prompt - this project uses email as the login field).

### 7. Run the development server

```bash
python manage.py runserver
```

The API is now available at `http://127.0.0.1:8000/`.

---

## API Documentation

Once the server is running:

| Resource            | URL                          |
|---------------------|-------------------------------|
| Swagger UI           | `http://127.0.0.1:8000/api/docs/`   |
| Redoc                | `http://127.0.0.1:8000/api/redoc/`  |
| Raw OpenAPI Schema    | `http://127.0.0.1:8000/api/schema/` |
| Django Admin          | `http://127.0.0.1:8000/admin/`      |

---

## Authentication Endpoints (`/api/v1/auth/`)

| Method | Endpoint                  | Description                          | Auth Required |
|--------|----------------------------|----------------------------------------|----------------|
| POST   | `/register/`                | Register as Student or Teacher          | No             |
| POST   | `/login/`                    | Obtain JWT access/refresh tokens         | No             |
| POST   | `/refresh/`                  | Refresh an access token                  | No             |
| POST   | `/logout/`                   | Blacklist a refresh token                | Yes            |
| POST   | `/change-password/`           | Change password (authenticated user)      | Yes            |
| POST   | `/forgot-password/`           | Request a password reset token            | No             |
| POST   | `/reset-password/`            | Reset password using the emailed token    | No             |

## Student Endpoints (`/api/v1/students/`)

| Method            | Endpoint     | Description                       | Auth Required        |
|-------------------|--------------|--------------------------------------|-----------------------|
| GET/POST/PUT/PATCH | `/me/`        | View/create/update own profile      | Yes (Student role)    |
| GET                | `/`           | List student profiles                | Yes                   |
| GET                | `/{id}/`      | Retrieve a single student profile    | Yes                   |

## Teacher Endpoints (`/api/v1/teachers/`)

| Method            | Endpoint     | Description                       | Auth Required        |
|-------------------|--------------|--------------------------------------|-----------------------|
| GET/POST/PUT/PATCH | `/me/`        | View/create/update own profile      | Yes (Teacher role)    |
| GET                | `/`           | List teacher profiles (free, per spec) | Yes                |
| GET                | `/{id}/`      | Retrieve a single teacher profile      | Yes                |

---

## Authentication Header Format
Authorization: Bearer <access_token>

---

## Running in Production

Set the settings module to production before running any management commands or
starting the app server:

```bash
export DJANGO_SETTINGS_MODULE=config.settings.production
```

Ensure `.env` in production has `DEBUG=False` and a real `ALLOWED_HOSTS` list -
`config/settings/production.py` will refuse to boot with `DEBUG=True`.

Example Gunicorn start command:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

Static files must be collected before deployment:

```bash
python manage.py collectstatic --noinput
```

---

## What's NOT Implemented Yet (Future Phases)

- Wallet / token balance and purchases
- Premium membership
- Lead matching / student-contact unlocking
- Payment gateway integration
- Notifications (email delivery, SMS/OTP verification)
- Reviews / ratings
- Search relevance ranking

---

## License

Proprietary - all rights reserved.
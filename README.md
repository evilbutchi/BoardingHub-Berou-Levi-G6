# BoardingHub

A Room, Tenant, and Billing Management System for a student boarding house.
This repository is **Phase 1**: project setup and the **Account Feature**.

**Stack:** Django (backend + templates), PostgreSQL / Supabase. No SQLite.

## Roles

| Role | Created by | Dashboard |
|------|-----------|-----------|
| Landlord | `createsuperuser` (automatically a Landlord) | `/dashboard/landlord/` |
| Caretaker | Landlord, via **Accounts → Add caretaker** | `/dashboard/caretaker/` |
| Tenant | Self-registration at `/register/` | `/dashboard/tenant/` |

Public registration only ever creates Tenants, so nobody can sign themselves up as a Landlord.

## Account Feature

- **Registration:** required fields, email format, unique username and email (case-insensitive), password confirmation, Django password validators. Passwords are hashed (PBKDF2).
- **Login / Logout:** clear error on bad credentials, POST-only logout that ends the session.
- **Protected pages:** `@login_required` / `role_required`; logged-out users are sent to the login page.
- **Role dashboards:** each role lands on its own dashboard with its own navigation. Opening another role's dashboard URL redirects back with an error message.
- **Profile:** view and edit your own name, email, contact number and photo. There is no user id in the profile URLs, so you can only reach your own.

## Setup

1. **Clone and create a virtual environment**
   ```bash
   git clone https://github.com/evilbutchi/BoardingHub-Berou-Levi-G6.git
   cd BoardingHub-Berou-Levi-G6
   python -m venv venv
   venv\Scripts\activate          # Windows
   # source venv/bin/activate     # macOS / Linux
   pip install -r requirements.txt
   ```

2. **Create the database** (PostgreSQL)
   ```sql
   CREATE DATABASE boardinghub;
   ```
   For Supabase, use the connection details from *Project Settings → Database* instead.

3. **Configure `.env`**
   ```bash
   copy .env.example .env         # Windows
   # cp .env.example .env         # macOS / Linux
   ```
   Fill in `SECRET_KEY` and the `DB_*` values. For Supabase set `DB_SSLMODE=require`.
   Generate a key with:
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
   ```

4. **Migrate and create the Landlord account**
   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver
   ```
   Open http://127.0.0.1:8000/.

## Running the tests

```bash
python manage.py test accounts
```
The tests run against PostgreSQL (Django creates and removes a temporary `test_boardinghub` database).

## Project layout

```
config/       project settings and root URLs
accounts/     custom User model, forms, views, decorators, tests
templates/    base layout and account pages
static/css/   stylesheet
```

## Security notes

- `.env`, `venv/`, and `__pycache__/` are git-ignored. Never commit credentials or Supabase keys.
- Uploaded profile photos go to `media/` (also git-ignored) and are limited to 2 MB.

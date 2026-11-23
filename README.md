# BoardingHub

A Room, Tenant, and Billing Management System for a student boarding house.
**Phase 1** delivered project setup and the **Account Feature**. **Phase 2 (this phase)** adds the core feature: **Monthly Billing and Payment Recording**.

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

## Core Feature: Monthly Billing and Payment Recording

BoardingHub exists to answer one question every month: *what does each tenant owe, and have they paid?* The core feature takes that from a room contract all the way to a recorded payment.

**How it flows**

1. **Landlord** adds rooms and creates a **contract** (tenant, room, monthly rate, deposit, start date). The room is then occupied.
2. **Caretaker** records each room's electricity and water meter once a month (**utility reading**). Saving it **generates the bill**: rent + electricity + water.
3. **Landlord** records **payments** against the bill (several partial payments are allowed). The bill is labelled **Unpaid**, **Partial**, **Paid** or **Overdue**.
4. **Tenant** sees only their own room, bills and payment history.

**Who can do what**

| | Landlord | Caretaker | Tenant |
|---|---|---|---|
| Rooms (add / edit / delete) | yes | | |
| Contracts (create / edit / end / delete) | yes | | own, read only |
| Utility readings | all | own | |
| Bills | all | | own, read only |
| Payments (record / edit / delete) | yes | | own, read only |

**Billing rules**

- A room has at most one active contract, and a tenant has at most one (enforced in the form and by database constraints).
- A room's meter is one chain: each reading's "previous" value is carried over from the room's last reading and can't be typed over. The current value can't be lower than the previous one.
- One reading and one bill per contract per month, in later months only, never for a month that hasn't started and never outside the contract period.
- Bill = monthly rate + electricity (kWh × rate) + water (m³ × rate). Rates and rent are copied onto the bill, so later changes don't rewrite old bills.
- Bills are due on the 10th of the following month. Rates and due day are set in `config/settings.py` (`ELECTRICITY_RATE_PER_KWH`, `WATER_RATE_PER_CUBIC_METER`, `BILL_DUE_DAY`) or `.env`.
- A payment must be more than zero, can't be dated in the future, and can't exceed the remaining balance.
- Only the latest reading of a room can be edited or deleted, and not once a payment exists against its bill. Contracts and rooms with history can't be deleted; end the contract instead.

**Data model** (all stored in PostgreSQL): `Room` ← `Contract` (→ tenant `User`) ← `UtilityReading` (→ recorder `User`) ← `Bill` ← `Payment` (→ recorder `User`). Every record keeps a foreign key to the user who created it.

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

5. **(Optional) Load demo data**
   ```bash
   python manage.py seed_demo
   ```
   Creates `demo_landlord`, `demo_caretaker`, `demo_tenant` and `demo_tenant2`, three rooms, one contract and two sample bills. All use the password `Demo-Pass-1234`. Use only on a development database.

## Running the tests

```bash
python manage.py test
```
The tests run against PostgreSQL (Django creates and removes a temporary `test_boardinghub` database).

## Project layout

```
config/       project settings and root URLs
accounts/     custom User model, forms, views, decorators, tests
billing/      rooms, contracts, readings, bills, payments (models, forms, views, services, tests)
docs/         PD2 completion report
templates/    base layout, account pages and billing pages
static/css/   stylesheet
```

## Security notes

- `.env`, `venv/`, and `__pycache__/` are git-ignored. Never commit credentials or Supabase keys.
- Uploaded profile photos go to `media/` (also git-ignored) and are limited to 2 MB.

## Branching

`main` holds stable code only. Work is merged through pull requests: `feature/<name>` → `develop` → `main`.

- `feature/rooms-contracts`: rooms and contracts
- `feature/billing-payments`: utility readings, bills and payments

# Presentation Proposal Testing Handbook

This guide covers automated tests against MySQL and manual checks of the public proposal endpoint. The endpoint is `POST /api/presentation-proposals/`; it accepts a file upload and does not require authentication.

## Do I need an HTML page?

No. The backend can be tested directly with Django's test client, Swagger UI, `curl`, or an API client such as Postman. Because the frontend and backend are separate, an HTML page is only needed for a browser-to-API integration check, not to verify the backend feature.

Swagger UI is available at `http://127.0.0.1:8000/api/swagger/`. Its request form should show the slides field as a file upload.

## 1. Prepare local configuration

Activate the project's virtual environment, then create a local environment file if you do not already have one:

```bash
source .venv/bin/activate
cp .env.example .env
```

Edit `.env`: values in `.env.example` are examples, not working database credentials. Set the values to match the MySQL container:

```dotenv
DEBUG=True
DB_NAME=your_local_database
DB_USER=your_mysql_user
DB_PASSWORD=your_mysql_password
DB_HOST=127.0.0.1
DB_PORT=3306
```

The host-side port should be `3306` if the container publishes `3306:3306`. If Django itself runs in another container, use the MySQL service name as `DB_HOST` and the container's internal port, usually `3306`.

Keep `.env` private; it is ignored by Git. Do not use a production database for development or tests.

## 2. Confirm MySQL is usable

The Python `mysqlclient` package also needs its operating-system MySQL client library. Check that the package can load:

```bash
python -c "import MySQLdb; print('mysqlclient is ready')"
```

If this reports a missing shared library, install the matching MySQL client runtime for your operating system. In this environment, Django previously reported that `libmysqlclient.so.21` was missing, so MySQL checks and tests could not run here yet.

Once the driver loads, apply the app migrations to the configured development database and confirm the proposal migration is applied:

```bash
python manage.py check
python manage.py migrate
python manage.py showmigrations shop
```

Look for `0017_presentationproposal` marked with `[X]` in the migration list.

## 3. Run the proposal tests using MySQL

Run the focused feature tests:

```bash
python manage.py test shop.tests.PresentationProposalApiTests
```

Django's test runner creates a separate test database, normally named `test_<DB_NAME>`, applies migrations there, and removes it afterward. The configured MySQL user therefore needs permission to create and drop that test database. These tests use temporary local file storage for uploaded test files, so they do not upload to the configured S3-compatible bucket.

The feature tests cover:

- Anonymous successful submission and the `201` response body.
- Optional organization and required form fields.
- Unsupported slide extensions and files larger than 20 MiB.
- Staff review and slide download link in Django admin.
- The limit of 10 anonymous submissions per IP per hour (`429` after the limit).

To run every app's tests, use `python manage.py test`. The existing `accounts.tests.UserTestCase.test_login` has an unrelated route mismatch: it posts to `/api/token/`, while the configured token endpoint is `/api/token/access/`. Prefer the focused feature-test command if that existing failure appears.

## 4. Submit a request manually

For local manual testing, set `DEBUG=True` in `.env` and restart the server. In debug mode uploads are stored under the project's `media/` directory, so no bucket account or bucket credentials are needed. Deployed environments with `DEBUG=False` continue using the configured S3-compatible storage and need valid bucket settings.

Start the server:

```bash
python manage.py runserver
```

Then submit a real PDF, PowerPoint, or PPTX file:

```bash
curl -i http://127.0.0.1:8000/api/presentation-proposals/ \
  -F 'full_name=Taylor Example' \
  -F 'biography=Short speaker biography' \
  -F 'organization=Example Organization' \
  -F 'phone_number=+15551234567' \
  -F 'topic=Building reliable APIs' \
  -F 'abstract=An abstract describing the presentation.' \
  -F 'slides=@/path/to/test.pdf'
```

Replace the sample values and file path. Both `organization` and `slides` are optional; omit either `-F` line to test that behavior. When slides are provided, only PDF, PPT, and PPTX files up to 20 MiB are accepted. `curl -F` sends `multipart/form-data`; do not manually set the `Content-Type` header because the client must add the multipart boundary.

Expected success response:

```http
HTTP/1.1 201 Created
```

```json
{"detail":"Proposal submitted successfully."}
```

The API does not return the proposal ID or provide public list/detail endpoints. Invalid or missing fields and invalid uploads return `400` with errors keyed by field. The rate limit returns `429`.

## 5. Review a submission in admin

Create an admin account if needed, then sign in at `http://127.0.0.1:8000/admin/`:

```bash
python manage.py createsuperuser
```

Open **Presentation proposals**, select the submitted proposal, and use **Download slides**. This page is staff-only; the public API has no endpoint for reading submitted proposals.

## Optional browser integration check

If you want to exercise the browser's `FormData` behavior, a tiny HTML form can be used, but it is not required for backend testing. The browser request should use `FormData` and should not set `Content-Type` manually; the browser supplies the multipart boundary.

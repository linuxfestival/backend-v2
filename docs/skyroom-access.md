# Skyroom credentials and room links

Each website user receives one separate saved Skyroom login. Its initial username
is the lowercase part before `@` (`ali@example.com` → `ali`).
If two users share the same email prefix, append `-{user_id}` to avoid a
collision. The initial Skyroom password is the saved phone number with only a
leading `+98` removed: `09123456789` stays `09123456789`; `+989123456789` becomes
`9123456789`. The website login password is never read, reused, or changed.

Credentials are created lazily on first user-panel access or admin export/email
queueing. They are encrypted in the database and remain stable across later
exports and emails. Editing a user's email/phone does not silently reset their
Skyroom login; the saved account must keep matching the manually imported account.
No Skyroom API account creation, room assignment, or password reset is performed.

## Admin

In **Shop → Presentations**, enable **Is Skyroom** for the relevant online
presentation and set **Skyroom room URL**. The URL is shown only in authenticated
Skyroom access responses for completed participants; it is not added to the
public presentation response. Credentials can be prepared before a room link is
available; the user panel should show a “link will be added” message for blank URLs.

Actions:

- **Accounts → Users → Export Skyroom credentials (Excel)** exports all selected
  users, or select all across pages to export all accounts.
- On a presentation edit page, **Download Skyroom Excel** at the top downloads
  one row per completed participant of that presentation, ready for Skyroom's
  user import, using saved credentials and configured room short addresses.
- **Shop → Presentations → Export participants’ Skyroom credentials (Excel)**
  exports one row per completed participant, limited to selected presentations.
  Admin exports work even before the Skyroom flag/link is configured; enabling
  that flag is still required for private user-panel access and email delivery.
- **Shop → Presentations → Email Skyroom credentials to participants** asks for
  confirmation, then queues one email per completed participant. Each email
  contains only that user's saved credentials and their selected room links.
- **Accounts → Skyroom emails** shows pending/sent/failed delivery states, attempts,
  and error classes. Staff can retry failed emails after fixing SMTP configuration.

The export follows Skyroom's positional user-import format, with **no header row**:
`username`, `password`, `nickname`, `rooms`, `access`, `email`, `mobile`,
`firstname`, `lastname`. The first row is a real user, not column labels.
Username and password are the same saved values returned to the user panel.
Room URLs of the form `/ch/account/room` produce comma-separated short room
addresses (`room`), never full URLs or presentation titles. Access is `normal`,
never presenter/operator. If no supported room URL is configured, both rooms and
access are blank: users can be imported, but room membership must be assigned
in Skyroom manually or by reimport after configuring a room URL. No wildcard
access is granted. This replaces the older seven-column participant report.
The format and `normal` role were verified against Skyroom's public user-import
component and [official user template](https://www.skyroom.online/panel/users-import-template.xlsx).
Phone/password cells are text to preserve leading zeroes, and all strings are
written as text to prevent spreadsheet formula execution.

Superusers can use the actions. Other staff need the explicit permissions
`accounts.export_skyroom_credentials` and/or `accounts.email_skyroom_credentials`.
Emails use the existing `MAIL_*` configuration, go through a durable outbox, retry
up to five times, and never reset credentials. The worker rechecks entitlement,
account activity, and email identity before delivery.
Changed email addresses require a new confirmed email action; old queued emails
are marked failed rather than sent to a stale address. Delivery is at least once if a
worker crashes after SMTP acceptance but before its database commit; duplicate
delivery uses the same credentials. No real emails are sent during implementation.

## Frontend contract

Call `GET /api/users/skyroom/` with `Authorization: Bearer <access_token>` from
the authenticated user dashboard after loading their purchased presentations.
This is a dedicated private response; do not put credentials in public user
serializers or presentation cards.

Example response (test values):

```json
{
  "username": "ali",
  "password": "09123456789",
  "presentations": [
    {
      "id": 12,
      "name": "Online workshop",
      "room_url": "https://www.skyroom.online/ch/example/room",
      "start": "2026-10-15T09:00:00+03:30"
    }
  ]
}
```

Add a **Skyroom access / ورود به اسکای‌روم** section with username and masked
password, explicit reveal/copy buttons, and a room link for each returned
presentation. Render room links with `target="_blank" rel="noopener noreferrer"`.
Only `COMPLETED` registrations are returned, including purchased bundle members
and confirmed free-coupon registrations. Pending carts and review-only payments
do not grant access. Show:

- `200`: render the credentials and purchased room links.
- `401`: refresh/re-authenticate using the existing login handling.
- `404`: hide the section or show “No registered online sessions”.
- `503` with `code=skyroom_not_configured`: show “Skyroom access will be available soon”.

The public presentation API gains `is_skyroom` for UI labels. Do not assume this
flag alone grants access. Do not log credential responses, put passwords in URL
parameters, or persist this response in localStorage; it uses `private, no-store`.
Changing the room link in admin updates the user-panel response immediately.

## Deployment

Set a new `SKYROOM_ENCRYPTION_KEY` in the backend deployment environment, generated
with `Fernet.generate_key()`. Back up and keep that key stable; an unrelated new
key cannot decrypt existing credentials. The compose file forwards it to the
backend. Apply accounts migration 0023 and shop migration 0027.

Install `deploy/skyroom-email.cron` as `/etc/cron.d/linuxfest-skyroom-emails`
(root-owned, mode 0644, trailing newline). It processes up to 25 queued emails
every minute with a process lock. The command can also be run explicitly:
`docker compose exec -T backend python manage.py send_skyroom_emails --limit 25`.

Deployment, Skyroom import, marking real presentations as Skyroom sessions, and
sending real participant emails require separate actions. This feature branch
does not perform those production operations.

# Presentation reminder emails

On a saved **Shop → Presentations → presentation** edit page, click
**Send reminder email**. The confirmation page shows the current recipient count,
an email preview, and a link to delivery status. Confirming queues one private
email per active user with a `COMPLETED` registration for that presentation,
including free/capacity-exempt and bundle registrations. Pending carts, failed
registrations, inactive accounts, and other presentations are excluded.

Reminders work for any presentation, not just Skyroom sessions. Persian emails
include the name, current start/end (Gregorian dates, Tehran time), the room URL
if Skyroom is enabled and configured, and `/profile/workshops`. No passwords or
Skyroom credentials are generated or emailed. Set `PUBLIC_SITE_URL` to override
the default `https://linuxfest.ir`; deployment compose uses `SITE_ADDRESS`.

Opening the page never sends or queues emails. Confirmation requires CSRF and a
signed token valid for one hour and bound to that presentation. Double-clicking
or repeating the same confirmation does not create duplicate jobs. Opening a
new confirmation page and confirming again intentionally creates a new batch.
Recipients are re-evaluated at confirmation, and registration/activity/email
identity are checked again before delivery. Changed recipient addresses require
a new batch; the old jobs fail safely instead of sending to a stale address.

Superusers can send reminders. Staff require `shop.send_presentation_reminders`
plus permission to view or change presentations. **Shop → Presentation reminders**
records pending/sent/failed status, attempts, sender, batch, and error class.
Staff can retry failed jobs with the same explicit send permission and the
appropriate admin access. Sent jobs are never reset by the retry action.

## Deployment

Apply `shop.0028_presentation_reminders`. Install
`deploy/presentation-reminder.cron` at `/etc/cron.d/linuxfest-presentation-reminders`
(root-owned, mode 0644, trailing newline). This processes up to 25 queued reminders
per minute using the existing `MAIL_*` configuration, with a process lock.
The worker retries failures with exponential backoff, up to five attempts:

```sh
docker compose exec -T backend python manage.py send_presentation_reminders --limit 25
```

Use `--limit 0` for a deployment check without sending any mail. Actual reminder
delivery is only requested by an administrator's explicit confirmation. SMTP
delivery is at least once: a crash after SMTP acceptance but before the database
commit can cause a duplicate on retry. No real participant emails are queued or
sent during tests or deployment checks.

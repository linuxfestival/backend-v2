# Editable carts and fresh checkout links

`POST /api/payments/pay_all/` always creates a fresh gateway link for the current
cart. A successful checkout retires previous unpaid links for that user and
releases their seat reservations. The new link becomes the only active checkout.
If checkout validation or gateway creation fails, the transaction rolls back:
the previous link and its reservations remain active.

Adding/removing an individual presentation or adding/removing a bundle retires
the user's old checkout links immediately. Users do not need to wait for the
payment timeout or a gateway verification request to edit their cart. Completed
purchases still cannot be removed. An original order snapshot is stored before
cart items are changed or deleted, including amount, presentation IDs/names,
bundle prices, accessories, and coupon.

## Old links paid later

Retiring a checkout invalidates it in our backend; it does not cancel the gateway
URL. If the gateway later verifies payment on that old authority:

1. Record the actual paid amount, provider reference, card details, and timestamp.
2. Mark `payment_state=COMPLETED` and `requires_manual_review=true`.
3. Do **not** register workshops, grant accessories, reduce coupon usage, or
   reserve capacity for the retired order.
4. Return HTTP 409 with `code=payment_requires_review`, `status=review_required`,
   `requires_manual_review=true`, `ref_id`, and `amount`.

This records money received without incorrectly fulfilling an outdated order.
Repeated callbacks/verification calls return the same review response and never
fulfil the order. Normal latest-link payments retain the existing success flow.

The callback redirect includes `ReviewRequired=1` and `RefID` for these payments.
The frontend must display **“Payment received; contact support with this
reference. Do not pay again.”**, not a generic payment failure or purchase success.
Also handle HTTP 409 `payment_requires_review` from the verification API and
check `requires_manual_review` before treating a payment-list record as a
fulfilled purchase. Disable repeated clicks while a checkout request is running.

## Reconciliation and support

The existing `python manage.py reconcile_pending_payments --limit 100` cron
command now checks both stale active payments and superseded links. It keeps
rechecking retired links after an earlier “not paid” result, since a user can pay
an old URL later. Attempts have a five-minute cooldown and are ordered by oldest
last-check time to rotate fairly when the limit is reached. Confirmed late
payments appear in the `manual_review` output counter.

In **Admin → Payments**, filter `Requires manual review = Yes` and
`Review resolved = No`. Staff can inspect the user's contact details, paid
reference/amount, retirement reason, and original `checkout_snapshot`. Add
support notes and mark the review resolved after handling it. These fields do
not perform refunds or grant registrations automatically; actual refund or
manual fulfilment remains an explicit support operation.

The completed-payment financial total includes these payments because funds
were actually received. Coupon usage excludes review payments because their
orders were not fulfilled.

No automatic emails, refunds, frontend edits, or production deployment are part
of this branch. On deployment, ensure the existing reconciliation cron runs the
updated backend container's management command.

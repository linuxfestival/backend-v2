# Registration and coupon admin accounting

Presentation admin shows **Completed registrations**, **Capacity-exempt
registrations**, and remaining capacity. Completed counts include both paid and
fully discounted purchases, including bundle members. Pending cart items and
pending gateway orders are not completed registrations. Exempt registrations
are a subset of completed registrations; they do not reduce available seats.

Coupon admin separates **Redeemed orders (recorded)** from **Discounted
registrations (recorded)**. One coupon checkout can register several workshops:
two redeemed orders may therefore correspond to six discounted registrations.

Previously, fully discounted checkouts completed immediately without creating a
payment record. The admin counted only completed gateway payments, so free
coupon orders were missing. New **Coupon redemptions** now record free and paid
coupon checkouts, the user, coupon, associated payment (when present), discounted
registrations, and a snapshot of the discount/capacity behavior. Repeat gateway
verification does not create duplicate redemptions. Late retired payments marked
for support review do not redeem coupons.

Known legacy gateway orders remain included in coupon counts without being
counted again when they also have a new redemption record. Historical free
checkouts have no reliable coupon attribution and are not fabricated or assigned
to a guessed coupon. Therefore coupon counts explicitly say **recorded**.
Presentation registration counts remain accurate for all existing registrations,
including old free orders, because their participation records already exist.

This branch builds on the already deployed editable-checkout branch. Merge
`feat/editable-payment-checkouts` into main before, or together with, this branch.

# Display capacity and checkout capacity

`Presentation.remained_capacity` and `Bundle.remaining_capacity` now count all
completed registrations, including capacity-exempt coupon registrations. Active
gateway reservations also reduce the displayed count; cart items without an
active checkout and retired checkout links do not. Values never fall below zero.

Checkout continues to preserve coupon capacity using its original calculation.
The new `checkout_remaining_capacity` field exposes that quota separately in
presentation and bundle responses. Bundle `is_available` remains based on that
checkout quota. Frontend purchase controls should use `checkout_remaining_capacity`
(or bundle `is_available`), while capacity labels use the existing display field.

Example: capacity 100, 41 completed registrations, 21 of which are exempt, and no
active reservations: displayed remaining is 59; checkout remaining is 80.
The admin shows both figures explicitly. No database migration is required.

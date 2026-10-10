# Presentation bundles

Admins create bundles under **Shop → Bundles**, with a name, optional description,
fixed price in Toman, at least two presentations/workshops, optional existing
bilingual tags, and an active flag. Price may be zero. Sales availability is
calculated automatically; remaining capacity is the smallest remaining capacity
among the members. A bundle becomes unavailable when disabled, missing members,
or when any member is full, started, or closed for registration.

## Frontend endpoints

| Method | Endpoint | Authentication | Behavior |
| --- | --- | --- | --- |
| GET | `/api/bundles/` | Public | List bundles, including unavailable bundles. |
| GET | `/api/bundles/{id}/` | Public | Bundle detail and live availability. |
| GET | `/api/bundles/cart/` | Bearer access token | Current user's pending bundle selections. |
| POST | `/api/bundles/{id}/add_to_cart/` | Bearer access token | Add all members together; no body required. Returns 201. |
| DELETE | `/api/bundles/{id}/remove_from_cart/` | Bearer access token | Remove the whole unpaid bundle. Returns 204. |
| POST | `/api/payments/pay_all/` | Bearer access token | Existing checkout; purchases bundles and standalone items together. |

Bundle responses include `id`, `name`, `description`, `price`, `original_price`,
`tags`, `presentations`, `is_active`, `remaining_capacity`, `is_available`, and
`unavailable_reason`. Both prices are Toman amounts. `original_price` is the sum
of current individual prices. Do not offer purchase when `is_available` is false.
Unavailable reasons: `inactive`, `insufficient_presentations`, `started`,
`registration_closed`, `sold_out`.

Bundle cart responses are an array of `{id, bundle, participation_ids}`. Here `id`
is the selection ID; add/remove URLs always use **bundle ID**, not selection ID.
The existing `/api/presentations/cart/` response remains an array of participation
records with an added nullable `bundle_selection` field. For the pending cart,
render only records with `bundle_selection: null` as standalone products, and
render bundles once from `/api/bundles/cart/`. Calculate the displayed price from
each standalone presentation cost plus each bundle's fixed price, never from its
members' individual prices. The checkout server always recalculates the charge.

After adding or removing a bundle, refresh both cart endpoints. Adding a bundle
converts overlapping standalone cart items into bundle members, preserving a
single participation per user/presentation. Purchased members and overlapping
bundles are rejected with HTTP 409; `already_purchased` includes the overlapping
`presentation_ids`. Individual removal of a bundled member returns 409 with code
`bundle_item`; offer removal of the whole bundle instead.

An active gateway payment prevents bundle removal or conversion of its items.
After the payment's reservation expires, removal verifies its provider status:
confirmed purchases cannot be removed; rejected payments can be removed; provider
errors return 503 and preserve the cart. This matches individual cart behavior.

## Checkout and purchase records

Checkout validates every member's registration and capacity under database locks.
Adding a bundle to a cart does not reserve seats. Starting a gateway payment
reserves one seat in each member, using the existing pending-payment lifetime and
reconciliation rules. A completed payment registers every member; workshops
remain visible individually in existing purchased-workshop responses.

Checkout charges each bundle once at its current fixed price. Once a provider
payment is started, the charge and members stay fixed even if the admin changes
the bundle. Payment-list responses include `bundle_snapshot`, an array containing
`bundle_id`, `name`, `price`, and `presentation_ids` captured at checkout.
Before a gateway payment starts, changing bundle membership invalidates the old
cart selection (`bundle_changed`); the user must remove and re-add it. Price
changes are reflected in the cart and next checkout. Free orders complete
immediately with 204 using the existing free-checkout behavior.

Coupons discount standalone presentations and, for unscoped coupons, accessories.
They never discount bundle prices or make bundled seats capacity-exempt.
Coupon minimum-item counts exclude bundle members. A bundle-only cart cannot
apply a coupon. Mixed-cart coupon validation and checkout enforce the same rules.

Existing frontend code can still display purchased members individually, but
bundle discovery/cart display requires the integrations described above.

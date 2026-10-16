# Late registration

Presentations have an `allow_registration_after_start` admin checkbox (default
false). Enable it only when registrations should remain possible after the
scheduled start. Both adding to the cart and checkout honor this setting;
registration must still be active, capacity checks still apply, and existing
purchases cannot be duplicated. Free/coupon and paid checkout keep the existing
payment protections. Bundles require every started member to opt in separately.

The public presentation API includes the boolean for clients. Existing frontend
buy buttons already honor `is_registration_active` and capacity, so no frontend
deployment is required. The override does not automatically expire at the end
time: close registration in admin when sales should stop.

Deployment: apply `shop.0029_late_registration`, set
`is_registration_active=True` and `allow_registration_after_start=True` only for
the presentation explicitly requested by the organizer. The migration defaults
the override to false for every presentation; it does not hardcode production
IDs or change any registration flags or historical purchases.

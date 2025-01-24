from django.contrib import admin

from shop.models import Presenter, Presentation, Participation, Coupon, Payment

admin.site.register(Presenter)
admin.site.register(Presentation)
admin.site.register(Participation)
admin.site.register(Coupon)
admin.site.register(Payment)

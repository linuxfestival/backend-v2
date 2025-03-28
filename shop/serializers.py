from rest_framework import serializers
from .models import Presentation, Participation, Payment, Presenter, Coupon, PresentationTag


class PresenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Presenter
        fields = ['first_name', 'last_name', 'email', 'description', 'avatar', 'linkedin']

class PresentationTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = PresentationTag
        fields = ['name', 'color']

class PresentationSerializer(serializers.ModelSerializer):
    remained_capacity = serializers.SerializerMethodField()
    presenters = PresenterSerializer(many=True)
    tags = PresentationTagSerializer(many=True, read_only=True)

    def get_remained_capacity(self, obj):
        return obj.get_remained_capacity()

    class Meta:
        model = Presentation
        fields = [
            'service_type', 'capacity', 'start', 'end', 'description', 'title', 'remained_capacity',
            'id', 'cost', 'presenters', 'is_registration_active', 'presentation_link', 'tags', 'morkopoloyor'
        ]
        extra_kwargs = {'id': {'read_only': True}, 'presentation_link': {'read_only': True}}


class CartSerializer(serializers.ModelSerializer):
    payment_state = serializers.CharField(source='get_payment_state_display')
    service_type = serializers.CharField(source='presentation.get_service_type_display')
    presentation = PresentationSerializer(read_only=True)

    class Meta:
        model = Participation
        fields = ['id', 'presentation', 'payment_state', 'service_type']
        extra_kwargs = {'service_type': {'read_only': True}, 'payment_state': {'read_only': True}
                        , 'presentation': {'read_only': True}, 'id': {'read_only': True}}


class ParticipationSerializer(serializers.ModelSerializer):
    presentation = PresentationSerializer(read_only=True)
    class Meta:
        fields = '__all__'
        model = Participation

class CouponSerializer(serializers.ModelSerializer):
    is_valid = serializers.BooleanField(default=False)
    class Meta:
        fields = ['percentage', 'is_valid']
        model = Coupon

    def get_is_valid(self, obj):
        return obj.is_valid()






class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['user', 'total_price', 'payment_state', 'ref_id', 'authority', 'id',
                  'card_pan', 'created_date', 'verified_date', 'coupon']
        extra_kwargs = {'id': {'read_only': True}}


class PayAllSerializer(serializers.ModelSerializer):
    coupon = serializers.CharField(required=False, allow_blank=True)
    accessories = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )

    class Meta:
        model = Payment
        fields = ['coupon', 'accessories']


class PaymentVerifySerializer(serializers.Serializer):
    authority = serializers.CharField()

class PaymentListSerializer(serializers.ModelSerializer):
    participations = ParticipationSerializer(many=True, read_only=True)
    class Meta:
        model = Payment
        fields = '__all__'
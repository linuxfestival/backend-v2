from rest_framework import serializers
from .models import Presentation, Participation, Payment, Presenter

class PresenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Presenter
        fields = ['first_name', 'last_name', 'email', 'description', 'avatar']

class PresentationSerializer(serializers.ModelSerializer):
    remained_capacity = serializers.SerializerMethodField()
    presenters = PresenterSerializer(many=True)

    def get_remained_capacity(self, obj):
        return obj.get_remained_capacity()

    class Meta:
        model = Presentation
        fields = [
            'service_type', 'capacity', 'start', 'end', 'description', 'title', 'remained_capacity',
            'pk', 'cost', 'presenters', 'is_registration_active', 'presentation_link'
        ]
        extra_kwargs = {'pk': {'read_only': True}, 'presentation_link': {'read_only': True}}

class ParticipationSerializer(serializers.ModelSerializer):
    payment_state = serializers.CharField(source='get_payment_state_display')
    service_type = serializers.CharField(source='presentation.get_service_type_display')
    presentation = PresentationSerializer(read_only=True)

    class Meta:
        model = Participation
        fields = ['pk', 'presentation', 'payment_state', 'service_type']
        extra_kwargs = {'pk': {'read_only': True}}

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['user', 'total_price', 'payment_state', 'payment_link', 'paymentID', 'trackID',
                  'verifyID', 'hashed_card_number', 'created_date', 'verified_date', 'coupon']
        extra_kwargs = {'pk': {'read_only': True}}

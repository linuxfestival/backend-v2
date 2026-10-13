from django.core.exceptions import ImproperlyConfigured
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .skyroom import credential_password, ensure_credential, room_data, user_presentations


class SkyroomRoomSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    room_url = serializers.URLField(allow_blank=True)
    start = serializers.DateTimeField()


class SkyroomAccessSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    presentations = SkyroomRoomSerializer(many=True)


class SkyroomAccessView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SkyroomAccessSerializer})
    def get(self, request):
        items = list(user_presentations(request.user))
        if not items:
            return Response({'detail': 'No completed Skyroom registrations.'}, status=404,
                            headers={'Cache-Control': 'private, no-store'})
        try:
            credential = ensure_credential(request.user)
            password = credential_password(credential)
        except ImproperlyConfigured:
            return Response({'detail': 'Skyroom access is not configured yet.', 'code': 'skyroom_not_configured'},
                            status=503, headers={'Cache-Control': 'private, no-store'})
        return Response({'username': credential.username, 'password': password, 'presentations': room_data(items)},
                        headers={'Cache-Control': 'private, no-store', 'Vary': 'Authorization'})

from .models import ContentDB
from rest_framework import serializers
from django.contrib.auth.models import User

class UserSerializer(serializers.ModelSerializer) :
     class Meta :
          model=User
          fields=['id','username','email']

class ContentSerializer(serializers.ModelSerializer) :
    user = UserSerializer(read_only=True)  # nested content
    class Meta :
        model =ContentDB
        fields="__all__"

# testing purpose only -- 13-10-25
from .models import WeeklySelection

class WeeklySelectionSerializer(serializers.ModelSerializer):
    content = ContentSerializer(read_only=True)  # nested content
    class Meta:
        model = WeeklySelection
        fields = "__all__"


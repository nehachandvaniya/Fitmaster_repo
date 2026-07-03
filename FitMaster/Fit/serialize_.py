from rest_framework import serializers
from .models import User
class user_serialize(serializers.ModelSerializer):
    class Meta:
        model = User
        # fields = ['id','name','email']
        fields= '__all__'
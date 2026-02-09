"""
Serializers for chat API
"""

from rest_framework import serializers
from django.contrib.auth.models import User
from .models import ChatConversation, Message, ChatGroup, ChatNotification, ChatArchive
from friendship.models import Friendship, FriendshipStatus

class UserSerializer(serializers.ModelSerializer):
    profile_pic = serializers.SerializerMethodField()
    online_status = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'profile_pic', 'online_status']
    
    def get_profile_pic(self, obj):
        if hasattr(obj, 'profile') and obj.profile.profile_pic:
            return obj.profile.profile_pic.url
        return None
    
    def get_online_status(self, obj):
        try:
            notification = ChatNotification.objects.get(user=obj)
            return {
                'is_online': notification.is_online,
                'last_active': notification.last_active
            }
        except ChatNotification.DoesNotExist:
            return {'is_online': False, 'last_active': None}


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    reply_to = serializers.SerializerMethodField()
    reactions = serializers.JSONField(read_only=True)
    is_mine = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id', 'sender', 'content', 'message_type', 'media_file',
            'file_name', 'file_size', 'latitude', 'longitude',
            'location_name', 'is_read', 'read_at', 'delivered_at',
            'created_at', 'reply_to', 'is_forwarded', 'original_sender',
            'reactions', 'is_deleted_for_everyone', 'is_mine'
        ]
        read_only_fields = ['created_at', 'updated_at']
    
    def get_reply_to(self, obj):
        if obj.reply_to:
            return {
                'id': obj.reply_to.id,
                'sender': obj.reply_to.sender.username,
                'content': obj.reply_to.content[:100],
                'message_type': obj.reply_to.message_type
            }
        return None
    
    def get_is_mine(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.sender == request.user
        return False


class ChatConversationSerializer(serializers.ModelSerializer):
    participants = UserSerializer(many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_participant = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatConversation  # Changed from Conversation
        fields = [
            'id', 'participants', 'conversation_type', 'name',
            'description', 'group_photo', 'is_private', 'created_at',
            'updated_at', 'last_message', 'last_message_time',
            'unread_count', 'other_participant'
        ]
    
    def get_last_message(self, obj):
        if obj.last_message:
            return {
                'content': obj.last_message,
                'time': obj.last_message_time
            }
        return None
    
    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.get_unread_count(request.user)
        return 0
    
    def get_other_participant(self, obj):
        request = self.context.get('request')
        if request and request.user and obj.conversation_type == 'direct':
            other = obj.get_other_participant(request.user)
            if other:
                serializer = UserSerializer(other)
                return serializer.data
        return None


class ChatGroupSerializer(serializers.ModelSerializer):
    conversation = ChatConversationSerializer(read_only=True)
    moderators = UserSerializer(many=True, read_only=True)
    admin = UserSerializer(read_only=True)
    
    class Meta:
        model = ChatGroup
        fields = [
            'id', 'conversation', 'max_members', 'join_by_invite',
            'allow_media', 'allow_forwarding', 'moderators', 'admin',
            'theme_color', 'custom_emoji'
        ]


class CreateMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['content', 'message_type', 'media_file', 'reply_to']
    
    def validate(self, data):
        # Validate file size if media
        if data.get('media_file'):
            max_size = 10 * 1024 * 1024  # 10MB
            if data['media_file'].size > max_size:
                raise serializers.ValidationError("File size exceeds 10MB limit")
        return data


class CreateGroupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(required=False, allow_blank=True)
    participant_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1
    )
    is_private = serializers.BooleanField(default=True)
    allow_media = serializers.BooleanField(default=True)


class ReactionSerializer(serializers.Serializer):
    message_id = serializers.UUIDField()
    emoji = serializers.CharField(max_length=10)

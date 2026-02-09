from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.core.cache import cache
from django.utils import timezone
import uuid

from django.db import transaction
import uuid
import logging

logger = logging.getLogger(__name__)
# Create your models here.



class ChatConversation(models.Model):
    CONVERSATION_TYPES = [
        ('direct', 'Direct Message'),
        ('group', 'Group Chat'),
        ('match', 'Match Conversation'),
        ('support', 'Support Chat'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participants = models.ManyToManyField(User, related_name='conversations', db_index=True)
    conversation_type = models.CharField(max_length=20, choices=CONVERSATION_TYPES, default='direct', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    
    # For group chats
    name = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    group_photo = models.ImageField(upload_to='group_photos/%Y/%m/', blank=True, null=True)
    is_private = models.BooleanField(default=True)
    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_chats')
    
    # Metadata
    last_message = models.TextField(blank=True, null=True)
    last_message_time = models.DateTimeField(null=True, blank=True)
    unread_count = models.JSONField(default=dict)  # Store {user_id: count}
    
    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['updated_at']),
            models.Index(fields=['conversation_type', 'is_active']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        if self.conversation_type == 'direct':
            users = list(self.participants.all())
            if len(users) == 2:
                return f"Chat: {users[0].username} & {users[1].username}"
        return self.name or f"Conversation {self.id}"
    
    def get_other_participant(self, user):
        """For direct messages, get the other user"""
        if self.conversation_type == 'direct':
            return self.participants.exclude(id=user.id).first()
        return None
    
    def update_last_message(self, message_content, sender):
        """Update conversation's last message info"""
        self.last_message = message_content[:100] + ('...' if len(message_content) > 100 else '')
        self.last_message_time = timezone.now()
        
        # Update unread counts for other participants
        for participant in self.participants.exclude(id=sender.id).only('id'):
            current_count = self.unread_count.get(str(participant.id), 0)
            self.unread_count[str(participant.id)] = current_count + 1
        
        self.save(update_fields=['last_message', 'last_message_time', 'updated_at', 'unread_count'])
        
        # Clear conversation cache
        cache_key = f"conversation_{self.id}"
        cache.delete(cache_key)
    
    def mark_as_read(self, user):
        """Mark all messages as read for a user"""
        with transaction.atomic():
            self.messages.filter(is_read=False).exclude(sender=user).update(
                is_read=True, 
                read_at=timezone.now()
            )
            
            # Reset unread count for this user
            if str(user.id) in self.unread_count:
                self.unread_count[str(user.id)] = 0
                self.save(update_fields=['unread_count'])
        
        # Clear cache
        cache.delete(f'unread_count_{user.id}')
    
    def get_unread_count(self, user):
        """Get unread message count for a user"""
        return self.unread_count.get(str(user.id), 0)
    
    @classmethod
    def get_or_create_direct_chat(cls, user1, user2):
        """Get or create a direct chat between two users with caching"""
        cache_key = f"direct_chat_{user1.id}_{user2.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        # Find existing conversation
        conversation = cls.objects.filter(
            conversation_type='direct',
            participants=user1
        ).filter(
            participants=user2
        ).first()
        
        if not conversation:
            # Create new conversation
            with transaction.atomic():
                conversation = cls.objects.create(conversation_type='direct')
                conversation.participants.add(user1, user2)
        
        # Cache for 5 minutes
        cache.set(cache_key, conversation, 300)
        return conversation


class Message(models.Model):
    """
    Enhanced Message model with rich features
    """
    MESSAGE_TYPES = [
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('file', 'File'),
        ('location', 'Location'),
        ('contact', 'Contact'),
        ('system', 'System Message'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        ChatConversation, 
        on_delete=models.CASCADE, 
        related_name='messages',
        null=True, 
        blank=True,
        db_index=True
    )
    sender = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='sent_messages',
        db_index=True
    )
    
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default='text', db_index=True)
    content = models.TextField()
    
    # For media messages
    media_file = models.FileField(upload_to='chat_media/%Y/%m/', blank=True, null=True)
    media_thumbnail = models.ImageField(upload_to='chat_thumbnails/', blank=True, null=True)
    file_size = models.IntegerField(blank=True, null=True)  # In bytes
    file_name = models.CharField(max_length=255, blank=True, null=True)
    
    # Location data
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    location_name = models.CharField(max_length=255, blank=True, null=True)
    
    # Status tracking
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Reply/Forward functionality
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    is_forwarded = models.BooleanField(default=False)
    original_sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='forwarded_messages')
    
    # Reactions
    reactions = models.JSONField(default=dict)
    
    # Delete status
    deleted_for = models.ManyToManyField(User, blank=True, related_name='deleted_messages')
    is_deleted_for_everyone = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['sender', 'created_at']),
            models.Index(fields=['is_read', 'created_at']),
            models.Index(fields=['message_type', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.sender.username}: {self.content[:50]}"
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if is_new and self.conversation:
            # Update conversation's last message
            self.conversation.update_last_message(self.content, self.sender)
            
            # Clear message cache
            cache_key = f"conversation_messages_{self.conversation_id}"
            cache.delete(cache_key)
    
    def mark_as_read(self):
        """Mark message as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
            
            # Clear cache
            cache.delete(f'unread_count_{self.sender.id}')
    
    def add_reaction(self, user, emoji):
        """Add reaction to message"""
        reactions = self.reactions.copy()
        reactions[str(user.id)] = emoji
        self.reactions = reactions
        self.save(update_fields=['reactions'])
    
    def remove_reaction(self, user):
        """Remove user's reaction"""
        reactions = self.reactions.copy()
        if str(user.id) in reactions:
            del reactions[str(user.id)]
            self.reactions = reactions
            self.save(update_fields=['reactions'])


class ChatGroup(models.Model):
    """
    Dedicated model for group chats with additional features
    """
    conversation = models.OneToOneField(ChatConversation, on_delete=models.CASCADE, related_name='chat_group')
    
    # Group settings
    max_members = models.IntegerField(default=50)
    join_by_invite = models.BooleanField(default=True)
    allow_media = models.BooleanField(default=True)
    allow_forwarding = models.BooleanField(default=True)
    
    # Group roles
    moderators = models.ManyToManyField(User, blank=True, related_name='moderated_groups')
    banned_users = models.ManyToManyField(User, blank=True, related_name='banned_from_groups')
    
    # Group metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_groups')
    theme_color = models.CharField(max_length=7, default='#0084FF')  # Hex color
    custom_emoji = models.JSONField(default=list, blank=True)  # List of custom emojis
    
    class Meta:
        verbose_name = 'Chat Group'
        verbose_name_plural = 'Chat Groups'
    
    def __str__(self):
        return self.conversation.name or f"Group {self.conversation.id}"
    
    def can_join(self, user):
        """Check if user can join the group"""
        if user in self.banned_users.all():
            return False
        if self.join_by_invite and user not in self.conversation.participants.all():
            return False
        return True
    
    def add_member(self, user, added_by=None):
        """Add member to group"""
        if self.can_join(user):
            self.conversation.participants.add(user)
            
            # Create system message
            if added_by:
                Message.objects.create(
                    conversation=self.conversation,
                    sender=added_by,
                    message_type='system',
                    content=f"{added_by.username} added {user.username} to the group"
                )
            return True
        return False
    
    def remove_member(self, user, removed_by=None):
        """Remove member from group"""
        self.conversation.participants.remove(user)
        
        # Create system message
        if removed_by:
            Message.objects.create(
                conversation=self.conversation,
                sender=removed_by,
                message_type='system',
                content=f"{removed_by.username} removed {user.username} from the group"
            )


class MessageStatus(models.Model):
    """
    Track detailed message status for each recipient
    """
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='statuses')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='message_statuses')
    
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
    ]
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='sent')
    updated_at = models.DateTimeField(auto_now=True)
    
    # For failed messages
    failure_reason = models.TextField(blank=True, null=True)
    retry_count = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ('message', 'user')
        verbose_name_plural = 'Message Statuses'
    
    def __str__(self):
        return f"{self.message.id} - {self.user.username}: {self.status}"


class ChatNotification(models.Model):
    """
    Model for chat notifications and preferences
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='chat_notifications')
    
    # Notification preferences
    notify_new_message = models.BooleanField(default=True)
    notify_message_sound = models.BooleanField(default=True)
    notify_message_preview = models.BooleanField(default=True)
    notify_group_mentions = models.BooleanField(default=True)
    
    # Privacy settings
    show_last_seen = models.BooleanField(default=True)
    show_online_status = models.BooleanField(default=True)
    show_read_receipts = models.BooleanField(default=True)
    allow_screenshots = models.BooleanField(default=True)
    
    # Chat settings
    theme = models.CharField(max_length=20, default='light', choices=[
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('system', 'System Default'),
    ])
    font_size = models.IntegerField(default=16)
    enter_to_send = models.BooleanField(default=True)
    
    # Media settings
    auto_download_media = models.BooleanField(default=False)
    media_download_size_limit = models.IntegerField(default=10485760)  # 10MB
    
    # Blocked users
    blocked_users = models.ManyToManyField(User, blank=True, related_name='blocked_by')
    
    # Last active timestamp
    last_active = models.DateTimeField(auto_now=True)
    is_online = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Chat settings for {self.user.username}"
    
    def update_online_status(self, is_online):
        """Update user's online status"""
        self.is_online = is_online
        self.last_active = timezone.now()
        self.save(update_fields=['is_online', 'last_active'])


class ChatArchive(models.Model):
    """
    Archive old conversations to optimize performance
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='archived_chats')
    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name='archives')
    archived_at = models.DateTimeField(auto_now_add=True)
    archived_until = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('user', 'conversation')
    
    def __str__(self):
        return f"{self.user.username} archived {self.conversation}"


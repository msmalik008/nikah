import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model

User = get_user_model()

class ProfileUpdateConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_authenticated:
            await self.accept()
            # Join user-specific room
            await self.channel_layer.group_add(
                f"user_{self.user.id}",
                self.channel_name
            )
        else:
            await self.close()
    
    async def disconnect(self, close_code):
        if hasattr(self, 'user') and self.user.is_authenticated:
            # Leave user-specific room
            await self.channel_layer.group_discard(
                f"user_{self.user.id}",
                self.channel_name
            )
    
    async def receive(self, text_data):
        # Handle incoming messages if needed
        pass
    
    async def profile_updated(self, event):
        # Send profile update to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'profile_update',
            'message': event['message'],
            'data': event.get('data', {})
        }))




class OnlineStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        self.user_group_name = f'user_{self.user.id}_status'
        
        # Join user's status group
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )
        
        # Update user as online
        await self.update_user_status(True)
        
        await self.accept()
    
    async def disconnect(self, close_code):
        # Leave user's status group
        await self.channel_layer.group_discard(
            self.user_group_name,
            self.channel_name
        )
        
        # Update user as offline
        await self.update_user_status(False)
    
    async def receive(self, text_data):
        # Handle status updates
        pass
    
    @database_sync_to_async
    def update_user_status(self, is_online):
        # Update user profile status
        if self.user.is_authenticated:
            profile = self.user.userprofile
            profile.is_online = is_online
            profile.save(update_fields=['is_online'])

class ActivityNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_authenticated:
            await self.accept()
            # Join user's notification group
            await self.channel_layer.group_add(
                f"notifications_{self.user.id}",
                self.channel_name
            )
        else:
            await self.close()
    
    async def disconnect(self, close_code):
        if hasattr(self, 'user') and self.user.is_authenticated:
            await self.channel_layer.group_discard(
                f"notifications_{self.user.id}",
                self.channel_name
            )
    
    async def receive(self, text_data):
        # Handle incoming messages
        pass
    
    async def send_notification(self, event):
        # Send notification to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'message': event['message'],
            'data': event.get('data', {})
        }))

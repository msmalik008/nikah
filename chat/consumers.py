import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from .models import ChatConversation, Message, ChatNotification

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.user = self.scope['user']
        
        # Check if user is a participant in the conversation
        if not await self.is_participant():
            await self.close()
            return
        
        self.room_group_name = f'chat_{self.conversation_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message_type = text_data_json.get('type', 'message')
        
        if message_type == 'message':
            await self.handle_message(text_data_json)
        elif message_type == 'typing':
            await self.handle_typing(text_data_json)
        elif message_type == 'read_receipt':
            await self.handle_read_receipt(text_data_json)
    
    async def handle_message(self, data):
        message_content = data['message']
        
        # Save message to database
        message = await self.save_message(message_content)
        
        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message_content,
                'sender': self.user.username,
                'message_id': str(message.id),
                'timestamp': message.created_at.isoformat()
            }
        )
    
    async def handle_typing(self, data):
        # Broadcast typing status
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user': self.user.username,
                'is_typing': data.get('is_typing', False)
            }
        )
    
    async def handle_read_receipt(self, data):
        # Handle read receipts
        pass
    
    async def chat_message(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'sender': event['sender'],
            'message_id': event['message_id'],
            'timestamp': event['timestamp']
        }))
    
    async def typing_indicator(self, event):
        # Send typing indicator
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'user': event['user'],
            'is_typing': event['is_typing']
        }))
    
    @database_sync_to_async
    def is_participant(self):
        return ChatConversation.objects.filter(
            id=self.conversation_id,
            participants=self.user
        ).exists()
    
    @database_sync_to_async
    def save_message(self, content):
        conversation = ChatConversation.objects.get(id=self.conversation_id)
        message = Message.objects.create(
            conversation=conversation,
            sender=self.user,
            content=content
        )
        conversation.update_last_message(content, self.user)
        return message


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        
        self.room_group_name = f'notifications_{self.user.id}'
        
        # Join notifications group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        # Handle notification preferences
        pass
    
    async def send_notification(self, event):
        await self.send(text_data=json.dumps(event))
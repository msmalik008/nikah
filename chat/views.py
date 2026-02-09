from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.core.cache import cache
from .models import ChatConversation, Message, ChatGroup, ChatNotification, ChatArchive
from friendship.models import Friendship
from .forms import *
from friendship.forms import *
from django.db.models import Prefetch
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from .serializers import (
    ChatConversationSerializer, MessageSerializer,
    CreateMessageSerializer, CreateGroupSerializer,
    UserSerializer, ChatGroupSerializer
)
from .models import *
from django.contrib.auth.models import User
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import json

# Create your views here.
class ChatView(LoginRequiredMixin, View):
    """Main chat interface view"""
    template_name = 'chat/chat.html'
    
    def get(self, request):
        return render(request, self.template_name, {
            'user_id': request.user.id,
            'username': request.user.username,
        })


class ConversationListView(APIView):
    """API endpoint for listing conversations"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        # Get conversations where user is a participant
        conversations = ChatConversation.objects.filter(
            participants=request.user,
            is_active=True
        ).prefetch_related(
            'participants',
            Prefetch('messages', queryset=Message.objects.order_by('-created_at')[:1])
        ).order_by('-updated_at')
        
        # Filter by type if provided
        conv_type = request.GET.get('type')
        if conv_type:
            conversations = conversations.filter(conversation_type=conv_type)
        
        # Pagination
        paginator = PageNumberPagination()
        paginator.page_size = 20
        result_page = paginator.paginate_queryset(conversations, request)
        
        serializer = ChatConversationSerializer(
            result_page,
            many=True,
            context={'request': request}
        )
        
        return paginator.get_paginated_response(serializer.data)


class ConversationDetailView(APIView):
    """API endpoint for conversation details and messages"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, conversation_id):
        conversation = get_object_or_404(
        ChatConversation,  # Changed from Conversation
        id=conversation_id,
        participants=request.user,
        is_active=True
    )
        
        # Mark messages as read
        conversation.mark_as_read(request.user)
        
        # Get messages with pagination
        messages = conversation.messages.filter(
            is_deleted_for_everyone=False
        ).exclude(
            deleted_for=request.user
        ).select_related('sender').order_by('-created_at')
        
        paginator = PageNumberPagination()
        paginator.page_size = 50
        result_page = paginator.paginate_queryset(messages, request)
        
        serializer = MessageSerializer(
            result_page,
            many=True,
            context={'request': request}
        )
        
        # Get conversation info
        conv_serializer = ChatConversationSerializer(
            conversation,
            context={'request': request}
        )
        
        return Response({
            'conversation': conv_serializer.data,
            'messages': paginator.get_paginated_response(serializer.data).data
        })
    
    def post(self, request, conversation_id):
        """Send a message in conversation"""
        conversation = get_object_or_404(
            ChatConversation,
            id=conversation_id,
            participants=request.user,
            is_active=True
        )
        
        serializer = CreateMessageSerializer(data=request.data)
        if serializer.is_valid():
            message = serializer.save(
                conversation=conversation,
                sender=request.user
            )
            
            # Update conversation
            conversation.update_last_message(message.content, request.user)
            
            message_serializer = MessageSerializer(
                message,
                context={'request': request}
            )
            
            return Response(message_serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class StartConversationView(APIView):
    """API endpoint to start a new conversation"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            other_user = request.user.__class__.objects.get(id=user_id)
        except request.user.__class__.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if conversation already exists
        conversation = ChatConversation.get_or_create_direct_chat(request.user, other_user)
        
        serializer = ChatConversationSerializer(
            conversation,
            context={'request': request}
        )
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CreateGroupView(APIView):
    """API endpoint to create a group chat"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        serializer = CreateGroupSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            
            # Create conversation
            conversation = ChatConversation.objects.create(
                conversation_type='group',
                name=data['name'],
                description=data.get('description', ''),
                is_private=data['is_private'],
                admin=request.user
            )
            
            # Add participants
            participant_ids = data['participant_ids']
            participants = request.user.__class__.objects.filter(id__in=participant_ids)
            conversation.participants.add(request.user, *participants)
            
            # Create chat group
            chat_group = ChatGroup.objects.create(
                conversation=conversation,
                created_by=request.user,
                allow_media=data.get('allow_media', True)
            )
            
            # Add creator as admin and moderator
            chat_group.moderators.add(request.user)
            
            # Create welcome message
            Message.objects.create(
                conversation=conversation,
                sender=request.user,
                message_type='system',
                content=f"{request.user.username} created the group"
            )
            
            group_serializer = ChatGroupSerializer(chat_group)
            
            return Response(group_serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MessageActionsView(APIView):
    """API endpoint for message actions (delete, react, etc.)"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, message_id):
        action = request.data.get('action')
        
        if not action:
            return Response(
                {'error': 'Action is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        message = get_object_or_404(
            Message,
            id=message_id,
            conversation__participants=request.user
        )
        
        if action == 'delete':
            delete_for_everyone = request.data.get('delete_for_everyone', False)
            
            if delete_for_everyone and message.sender != request.user:
                return Response(
                    {'error': 'You can only delete your own messages for everyone'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if delete_for_everyone:
                message.delete_for_everyone()
            else:
                message.delete_for_user(request.user)
            
            return Response({'success': True})
        
        elif action == 'react':
            emoji = request.data.get('emoji')
            if not emoji:
                return Response(
                    {'error': 'Emoji is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            message.add_reaction(request.user, emoji)
            
            return Response({
                'success': True,
                'reactions': message.reactions
            })
        
        elif action == 'unreact':
            message.remove_reaction(request.user)
            
            return Response({
                'success': True,
                'reactions': message.reactions
            })
        
        return Response(
            {'error': 'Invalid action'},
            status=status.HTTP_400_BAD_REQUEST
        )


class SearchMessagesView(APIView):
    """API endpoint for searching messages"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        query = request.GET.get('q', '').strip()
        
        if not query or len(query) < 2:
            return Response(
                {'error': 'Search query must be at least 2 characters'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Search in user's conversations
        messages = Message.objects.filter(
            conversation__participants=request.user,
            content__icontains=query,
            is_deleted_for_everyone=False
        ).exclude(
            deleted_for=request.user
        ).select_related('sender', 'conversation').order_by('-created_at')
        
        paginator = PageNumberPagination()
        paginator.page_size = 20
        result_page = paginator.paginate_queryset(messages, request)
        
        serializer = MessageSerializer(
            result_page,
            many=True,
            context={'request': request}
        )
        
        return paginator.get_paginated_response(serializer.data)


class ChatSettingsView(APIView):
    """API endpoint for chat settings"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        notifications, created = ChatNotification.objects.get_or_create(user=request.user)
        
        return Response({
            'notify_new_message': notifications.notify_new_message,
            'notify_message_sound': notifications.notify_message_sound,
            'notify_message_preview': notifications.notify_message_preview,
            'show_last_seen': notifications.show_last_seen,
            'show_online_status': notifications.show_online_status,
            'show_read_receipts': notifications.show_read_receipts,
            'theme': notifications.theme,
            'font_size': notifications.font_size,
            'enter_to_send': notifications.enter_to_send,
            'auto_download_media': notifications.auto_download_media,
            'media_download_size_limit': notifications.media_download_size_limit,
            'blocked_users': UserSerializer(
                notifications.blocked_users.all(),
                many=True
            ).data
        })
    
    def put(self, request):
        notifications, created = ChatNotification.objects.get_or_create(user=request.user)
        
        for field in [
            'notify_new_message', 'notify_message_sound', 'notify_message_preview',
            'show_last_seen', 'show_online_status', 'show_read_receipts',
            'theme', 'font_size', 'enter_to_send', 'auto_download_media',
            'media_download_size_limit'
        ]:
            if field in request.data:
                setattr(notifications, field, request.data[field])
        
        # Handle blocked users
        if 'blocked_users' in request.data:
            blocked_ids = request.data['blocked_users']
            notifications.blocked_users.set(
                request.user.__class__.objects.filter(id__in=blocked_ids)
            )
        
        notifications.save()
        
        return Response({'success': True})


class UnreadCountView(APIView):
    """API endpoint for unread message count"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        # Check cache first
        cache_key = f'unread_count_{request.user.id}'
        cached_count = cache.get(cache_key)
        
        if cached_count is not None:
            return Response({'count': cached_count})
        
        # Calculate unread count
        count = Message.objects.filter(
            conversation__participants=request.user,
            is_read=False
        ).exclude(
            sender=request.user
        ).exclude(
            deleted_for=request.user
        ).count()
        
        # Cache for 5 minutes
        cache.set(cache_key, count, 300)
        
        return Response({'count': count})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def upload_chat_media(request):
    """Upload media for chat"""
    if 'file' not in request.FILES:
        return Response(
            {'error': 'No file provided'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    file = request.FILES['file']
    
    # Validate file type
    allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'video/mp4', 'audio/mpeg']
    if file.content_type not in allowed_types:
        return Response(
            {'error': 'File type not allowed'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate file size (10MB max)
    max_size = 10 * 1024 * 1024
    if file.size > max_size:
        return Response(
            {'error': 'File size exceeds 10MB limit'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Save file (in production, upload to cloud storage)
    # For now, return mock response
    return Response({
        'url': f'/media/chat_media/{file.name}',
        'filename': file.name,
        'size': file.size,
        'type': file.content_type
    })


@login_required
def send_message(request, user_id):
    """Send a message to another user"""
    if request.method == 'POST':
        receiver = get_object_or_404(User, id=user_id)
        
        # Check if receiver's profile is visible
        try:
            receiver_profile = receiver.profile
            if not receiver_profile.is_visible:
                messages.error(request, "Cannot send message to this user.")
                return redirect('dashboard', tab='discover')
        except Profile.DoesNotExist:
            messages.error(request, "User profile not found.")
            return redirect('dashboard', tab='discover')
        
        form = MessageForm(
            request.POST,
            sender=request.user,
            receiver=receiver
        )
        
        if form.is_valid():
            # Get or create conversation
            conversation = ChatConversation.get_or_create_direct_chat(
                request.user,
                receiver
            )
            
            # Create message
            message = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                content=form.cleaned_data['content']
            )
            
            # Update conversation timestamp
            conversation.save()
            
            messages.success(request, "Message sent successfully!")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Message sent successfully',
                    'message_id': str(message.id)
                })
        else:
            for error in form.errors.values():
                messages.error(request, error[0])
        
        return redirect('view_profile', user_id=user_id)
    
    return redirect('dashboard', tab='discover')


@login_required
def get_chat_friends(request):
    """Get friends list for chat widget (AJAX)"""
    try:
        friends = Friendship.get_friends(request.user)
        
        # Separate online and offline friends
        online_friends = []
        offline_friends = []
        
        for friend in friends:
            # Check if friend is online (you need to implement this logic)
            is_online = friend.last_seen and (timezone.now() - friend.last_seen) < timedelta(minutes=5)
            
            friend_data = {
                'id': friend.id,
                'username': friend.username,
                'full_name': friend.get_full_name(),
                'profile_pic': friend.profile.profile_pic.url if friend.profile.profile_pic else None,
                'is_online': is_online,
                'last_seen': friend.last_seen if hasattr(friend, 'last_seen') else None,
            }
            
            if is_online:
                online_friends.append(friend_data)
            else:
                offline_friends.append(friend_data)
        
        context = {
            'online_friends': online_friends,
            'offline_friends': offline_friends,
        }
        
        return render(request, 'quizapp/partials/chat_friends.html', context)
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


class MessageView(LoginRequiredMixin, View):
    """View for sending and viewing messages with a specific user"""
    template_name = 'chat/message_thread.html'
    
    def get(self, request, receiver_id):
        """Display message thread with a specific user"""
        try:
            receiver = get_object_or_404(User, id=receiver_id)
            
            # Check if receiver's profile is visible
            try:
                receiver_profile = receiver.userprofile
                if not receiver_profile.is_visible:
                    messages.error(request, "Cannot message this user.")
                    return redirect('dashboard')
            except AttributeError:
                messages.error(request, "User profile not found.")
                return redirect('dashboard')
            
            # Check if users can message each other
            can_message = self._can_message(request.user, receiver)
            if not can_message['allowed']:
                messages.error(request, can_message['message'])
                return redirect('dashboard')
            
            # Get or create conversation
            conversation = ChatConversation.get_or_create_direct_chat(
                request.user,
                receiver
            )
            
            # Get messages for this conversation
            messages_list = Message.objects.filter(
                conversation=conversation,
                is_deleted_for_everyone=False
            ).exclude(
                deleted_for=request.user
            ).select_related('sender').order_by('created_at')
            
            # Mark messages as read
            unread_messages = messages_list.filter(
                is_read=False
            ).exclude(sender=request.user)
            
            if unread_messages.exists():
                unread_messages.update(is_read=True, read_at=timezone.now())
                
                # Clear cache
                cache.delete(f'unread_count_{request.user.id}')
            
            # Paginate messages
            paginator = PageNumberPagination()
            paginator.page_size = 50
            result_page = paginator.paginate_queryset(
                messages_list,
                request
            )
            
            # Prepare context
            context = {
                'receiver': receiver,
                'conversation': conversation,
                'messages': result_page,
                'form': MessageForm(),
                'is_paginated': paginator.page.has_other_pages(),
                'page_obj': paginator.page,
                'paginator': paginator,
                'can_message': True,
                'user_id': request.user.id,
                'username': request.user.username,
                'receiver_profile_pic': self._get_profile_pic(receiver),
            }
            
            # If AJAX request, return JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                serializer = MessageSerializer(
                    result_page,
                    many=True,
                    context={'request': request}
                )
                return JsonResponse({
                    'messages': serializer.data,
                    'has_next': paginator.page.has_next(),
                    'next_page': paginator.page.next_page_number() if paginator.page.has_next() else None
                })
            
            return render(request, self.template_name, context)
            
        except Exception as e:
            messages.error(request, f"Error loading messages: {str(e)}")
            return redirect('dashboard')
    
    def post(self, request, receiver_id):
        """Send a message to a user"""
        try:
            receiver = get_object_or_404(User, id=receiver_id)
            
            # Check if users can message each other
            can_message = self._can_message(request.user, receiver)
            if not can_message['allowed']:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': can_message['message']
                    }, status=403)
                messages.error(request, can_message['message'])
                return redirect('view_profile', user_id=receiver_id)
            
            # Initialize form with sender and receiver
            form = MessageForm(
                request.POST,
                sender=request.user,
                receiver=receiver
            )
            
            if form.is_valid():
                # Get or create conversation
                conversation = ChatConversation.get_or_create_direct_chat(
                    request.user,
                    receiver
                )
                
                # Create message
                message = Message.objects.create(
                    conversation=conversation,
                    sender=request.user,
                    content=form.cleaned_data['content']
                )
                
                # Update conversation
                conversation.update_last_message(
                    form.cleaned_data['content'],
                    request.user
                )
                
                # Clear cache
                cache.delete(f'unread_count_{receiver.id}')
                
                # Prepare response data
                message_data = {
                    'id': str(message.id),
                    'content': message.content,
                    'sender': {
                        'id': request.user.id,
                        'username': request.user.username
                    },
                    'created_at': message.created_at.isoformat(),
                    'is_mine': True
                }
                
                # If AJAX request, return JSON
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': 'Message sent successfully',
                        'message_data': message_data,
                        'conversation_id': str(conversation.id)
                    })
                
                messages.success(request, "Message sent successfully!")
                return redirect('chat:send_message', receiver_id=receiver_id)
            
            else:
                # Form validation failed
                errors = {}
                for field, field_errors in form.errors.items():
                    errors[field] = field_errors[0] if field_errors else ''
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'errors': errors
                    }, status=400)
                
                for error in form.errors.values():
                    messages.error(request, error[0])
                
                return redirect('view_profile', user_id=receiver_id)
                
        except Exception as e:
            error_msg = f"Error sending message: {str(e)}"
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': error_msg
                }, status=500)
            
            messages.error(request, error_msg)
            return redirect('dashboard')
    
    def _can_message(self, sender, receiver):
        """Check if users can message each other"""
        # Can't message yourself
        if sender == receiver:
            return {
                'allowed': False,
                'message': "You cannot message yourself."
            }
        
        # Check if receiver has blocked sender
        try:
            receiver_notifications = ChatNotification.objects.get(user=receiver)
            if sender in receiver_notifications.blocked_users.all():
                return {
                    'allowed': False,
                    'message': "This user has blocked you."
                }
        except ChatNotification.DoesNotExist:
            pass
        
        # Check if sender has blocked receiver
        try:
            sender_notifications = ChatNotification.objects.get(user=sender)
            if receiver in sender_notifications.blocked_users.all():
                return {
                    'allowed': False,
                    'message': "You have blocked this user."
                }
        except ChatNotification.DoesNotExist:
            pass
        
        # Check if receiver's profile is visible
        try:
            receiver_profile = receiver.userprofile
            if not receiver_profile.is_visible:
                return {
                    'allowed': False,
                    'message': "Cannot message this user."
                }
        except AttributeError:
            return {
                'allowed': False,
                'message': "User profile not found."
            }
        
        # Check friendship (if required by your app rules)
        # You can modify this based on your requirements
        try:
            from friendship.models import Friendship
            are_friends = Friendship.are_friends(sender, receiver)
            
            if not are_friends:
                return {
                    'allowed': False,
                    'message': "You can only message friends."
                }
        except ImportError:
            # If friendship app is not installed, skip this check
            pass
        
        return {
            'allowed': True,
            'message': "Can message"
        }
    
    def _get_profile_pic(self, user):
        """Get user's profile picture URL"""
        try:
            if hasattr(user, 'userprofile') and user.userprofile.profile_pic:
                return user.userprofile.profile_pic.url
        except AttributeError:
            pass
        return None
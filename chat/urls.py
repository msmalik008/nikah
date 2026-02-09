from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('api/chat/conversations/', views.ConversationListView.as_view(), name='conversation_list'),
    path('api/chat/conversations/<uuid:conversation_id>/', views.ConversationDetailView.as_view(), name='conversation_detail'),
    path('api/chat/conversations/start/', views.StartConversationView.as_view(), name='start_conversation'),
    path('api/chat/groups/create/', views.CreateGroupView.as_view(), name='create_group'),
    path('api/chat/messages/<uuid:message_id>/actions/', views.MessageActionsView.as_view(), name='message_actions'),
    path('api/chat/messages/search/', views.SearchMessagesView.as_view(), name='search_messages'),
    path('api/chat/settings/', views.ChatSettingsView.as_view(), name='chat_settings'),
    path('api/chat/unread-count/', views.UnreadCountView.as_view(), name='unread_count'),
    path('api/chat/upload-media/', views.upload_chat_media, name='upload_chat_media'),
    path('chat/friends/', views.get_chat_friends, name='get_chat_friends'),
    # path('message/<int:receiver_id>/', views.MessageView.as_view(), name='send_message'),
    path('message/send/<int:user_id>/', views.send_message, name='send_message'),
    path('chat/', views.ChatView.as_view(), name='chat'),
]
from django.urls import path
from . import views

app_name = 'friendship'

urlpatterns = [
    # Friends management with tabs
    path('friends/', views.FriendshipManagementView.as_view(), {'tab': 'friends'}, name='friends'),
    path('friends/sent/', views.FriendshipManagementView.as_view(), {'tab': 'sent'}, name='sent_requests'),
    path('friends/received/', views.FriendshipManagementView.as_view(), {'tab': 'received'}, name='received_requests'),
    path('friends/blocked/', views.FriendshipManagementView.as_view(), {'tab': 'blocked'}, name='blocked_users'),
    path('friends/restricted/', views.FriendshipManagementView.as_view(), {'tab': 'restricted'}, name='restricted_users'),
    
    # Legacy view for viewing other user's friends (keep this separate)
    path('friends/<int:user_id>/', views.FriendsView.as_view(), name='view_friends'),

    path('send/<int:user_id>/', views.send_friend_request, name='send_friend_request'),
    path('accept/<int:user_id>/', views.accept_friend_request, name='accept_friend_request'),
    path('reject/<int:user_id>/', views.reject_friend_request, name='reject_friend_request'),
    path('cancel/<int:user_id>/', views.cancel_friend_request, name='cancel_friend_request'),
    path('withdraw-rejection/<int:user_id>/', views.withdraw_rejection, name='withdraw_rejection'),
    path('remove/<int:user_id>/', views.remove_friend, name='remove_friend'),
    path('block/<int:user_id>/', views.block_user, name='block_user'),
    path('unblock/<int:user_id>/', views.unblock_user, name='unblock_user'),


    # Likes management page
    path('likes/', views.LikesManagementView.as_view(), name='get_likes'),
    path('api/likes/mutual/', views.MutualLikesView.as_view(), name='mutual_likes'),
    path('api/likes/sent/', views.SentLikesView.as_view(), name='sent_likes'),
    path('api/likes/received/', views.ReceivedLikesView.as_view(), name='received_likes'),
    path('like/<int:user_id>/', views.LikeProfileView.as_view(), name='like_profile'),
    path('unlike/<int:user_id>/', views.UnlikeProfileView.as_view(), name='unlike_profile'),
    path('check-mutual/<int:user_id>/', views.CheckMutualLikeView.as_view(), name='check_mutual'),


]

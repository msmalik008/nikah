from django.urls import path
from . import views

app_name = 'friendship'

urlpatterns = [
    path('send/<int:user_id>/', views.send_friend_request, name='send_friend_request'),
    path('accept/<int:user_id>/', views.accept_friend_request, name='accept_friend_request'),
    path('reject/<int:user_id>/', views.reject_friend_request, name='reject_friend_request'),
    path('cancel/<int:user_id>/', views.cancel_friend_request, name='cancel_friend_request'),
    path('withdraw-rejection/<int:user_id>/', views.withdraw_rejection, name='withdraw_rejection'),
    path('remove/<int:user_id>/', views.remove_friend, name='remove_friend'),
    path('block/<int:user_id>/', views.block_user, name='block_user'),
    path('unblock/<int:user_id>/', views.unblock_user, name='unblock_user'),

    path('like/<int:user_id>/', views.LikeProfileView.as_view(), name='like_profile'),
    path('check-mutual/<int:user_id>/', views.CheckMutualLikeView.as_view(), name='check_mutual'),
    path('likes/', views.GetLikesView.as_view(), name='get_likes'),
]

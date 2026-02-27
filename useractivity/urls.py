# useractivity/urls.py - Add these URLs

from django.urls import path
from . import views

app_name = 'useractivity'

urlpatterns = [
    # Timeline
    path('timeline/', views.TimelineView.as_view(), name='timeline'),
    
    # API endpoints
    path('api/posts/', views.PostAPIView.as_view(), name='api_posts'),
    path('api/activity/recent/', views.RecentActivityAPIView.as_view(), name='recent_activity'),
    path('api/create-post/', views.CreatePostView.as_view(), name='create_post_api'),
    
    # Post actions
    path('post/create/', views.CreatePostView.as_view(), name='create_post'),
    path('post/<int:pk>/delete/', views.DeletePostView.as_view(), name='delete_post'),
    path('post/<int:post_id>/like/', views.LikePostView.as_view(), name='like_post'),
    path('post/<int:post_id>/comment/', views.CommentPostView.as_view(), name='comment_post'),
    path('post/<int:post_id>/share/', views.SharePostView.as_view(), name='share_post'),
    path('post/<int:post_id>/bookmark/', views.BookmarkPostView.as_view(), name='bookmark_post'),
    path('post/<int:post_id>/like/', views.toggle_post_like, name='toggle_post_like'),
    
    # Comment actions
    path('post/comment/add/', views.add_comment, name='add_comment'),
    path('comment/<int:comment_id>/like/', views.LikeCommentView.as_view(), name='like_comment'),
    path('comment/<int:comment_id>/delete/', views.delete_comment, name='delete_comment'),
    

    # Utility endpoints
    path('post/<int:post_id>/comments/', views.get_post_comments, name='get_post_comments'),
    path('post/<int:post_id>/likes/', views.get_post_likes, name='get_post_likes'),
    
    # Activity stream
    path('activity/', views.ActivityStreamView.as_view(), name='activity_stream'),
    
    # User posts
    path('user/<int:user_id>/posts/', views.UserPostsView.as_view(), name='user_posts'),
]
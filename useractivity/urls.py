# useractivity/urls.py
from django.urls import path
from . import views

app_name = 'useractivity'

urlpatterns = [
    # Timeline
    path('timeline/', views.TimelineView.as_view(), name='timeline'),
    
    # Post actions
    path('post/create/', views.CreatePostView.as_view(), name='create_post'),
    path('post/<int:pk>/delete/', views.DeletePostView.as_view(), name='delete_post'),
    path('post/<int:post_id>/like/', views.LikePostView.as_view(), name='like_post'),
    path('post/<int:post_id>/comment/', views.CommentPostView.as_view(), name='comment_post'),
    path('post/<int:post_id>/share/', views.SharePostView.as_view(), name='share_post'),
    path('post/<int:post_id>/bookmark/', views.BookmarkPostView.as_view(), name='bookmark_post'),
    
    # Comment actions
    path('comment/<int:comment_id>/like/', views.LikeCommentView.as_view(), name='like_comment'),
    
    # Activity stream
    path('activity/', views.ActivityStreamView.as_view(), name='activity_stream'),
    
    # User posts
    path('user/<int:user_id>/posts/', views.UserPostsView.as_view(), name='user_posts'),
]
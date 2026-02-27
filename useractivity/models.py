# useractivity/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()

class Post(models.Model):
    """Timeline posts"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
    content = models.TextField()
    image = models.ImageField(upload_to='posts/%Y/%m/%d/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    likes_count = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"Post #{self.id} by {self.user.username}"
    
    def update_counts(self):
        """Update like and comment counts"""
        self.likes_count = self.likes.count()
        self.comments_count = self.comments.count()
        self.save(update_fields=['likes_count', 'comments_count'])


class Comment(models.Model):
    """Comments on posts"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments')
    content = models.TextField()
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    likes_count = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"Comment #{self.id} by {self.user.username}"


class PostLike(models.Model):
    """Likes on posts"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_likes')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['post', 'user']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'post']),
            models.Index(fields=['post', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} likes post #{self.post.id}"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.post.update_counts()


class CommentLike(models.Model):
    """Likes on comments"""
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comment_likes')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['comment', 'user']
    
    def __str__(self):
        return f"{self.user.username} likes comment #{self.comment.id}"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.comment.likes_count = self.comment.likes.count()
        self.comment.save(update_fields=['likes_count'])


class Share(models.Model):
    """Post shares"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='shares')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shares')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['post', 'user']
    
    def __str__(self):
        return f"{self.user.username} shared post #{self.post.id}"


class Bookmark(models.Model):
    """Bookmarked posts"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='bookmarks')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookmarks')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['post', 'user']
    
    def __str__(self):
        return f"{self.user.username} bookmarked post #{self.post.id}"


# useractivity/models.py
class Activity(models.Model):
    """User activity stream/feed"""
    ACTIVITY_TYPES = [
        ('post_created', 'Post Created'),
        ('post_liked', 'Post Liked'),
        ('comment_created', 'Comment Created'),
        ('comment_liked', 'Comment Liked'),
        ('post_shared', 'Post Shared'),
        ('post_bookmarked', 'Post Bookmarked'),
        ('profile_viewed', 'Profile Viewed'),
        ('profile_liked', 'Profile Liked'),
        ('mutual_match', 'Mutual Match'),
        ('friend_added', 'Friend Added'),
        ('match_created', 'Match Created'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='feed_activities')
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPES)
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                   related_name='targeted_feed_activities')
    # CHANGE THESE TWO LINES: Remove 'posts.' prefix
    post = models.ForeignKey('Post', on_delete=models.CASCADE, null=True, blank=True)
    comment = models.ForeignKey('Comment', on_delete=models.CASCADE, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['activity_type']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.get_activity_type_display()}"
    
    @classmethod
    def create_activity(cls, user, activity_type, **kwargs):
        """Helper to create activity with proper relations"""
        activity = cls.objects.create(
            user=user,
            activity_type=activity_type,
            target_user=kwargs.get('target_user'),
            post=kwargs.get('post'),
            comment=kwargs.get('comment'),
            metadata=kwargs.get('metadata', {})
        )
        return activity
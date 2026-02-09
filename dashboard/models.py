from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
import uuid
# Create your models here.

class Like(models.Model):
    """Enhanced Like model with better mutual matching"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    liker = models.ForeignKey(User, related_name='given_likes', on_delete=models.CASCADE)
    liked = models.ForeignKey(User, related_name='received_likes', on_delete=models.CASCADE)
    is_mutual = models.BooleanField(default=False)  # Make sure this field exists
    notified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('liker', 'liked')
        indexes = [
            models.Index(fields=['liker', 'is_mutual']),
            models.Index(fields=['liked', 'is_mutual']),
        ]
    
    def __str__(self):
        return f"{self.liker.username} → {self.liked.username} (mutual: {self.is_mutual})"
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Check for mutual like
        if is_new:
            self.check_mutual_like()
    
    def check_mutual_like(self):
        """Check and update mutual like status"""
        reverse_like = Like.objects.filter(
            liker=self.liked,
            liked=self.liker
        ).first()
        
        if reverse_like and not self.is_mutual:
            self.is_mutual = True
            reverse_like.is_mutual = True
            
            # Save both
            self.save(update_fields=['is_mutual'])
            reverse_like.save(update_fields=['is_mutual'])
            
            # Clear cache
            from django.core.cache import cache
            cache.delete(f'mutual_matches_{self.liker_id}')
            cache.delete(f'mutual_matches_{self.liked_id}')
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.db.models import Q, Count, Prefetch, OuterRef, Subquery
from django.utils import timezone
from django.core.cache import cache
from django.core.paginator import Paginator, Page
from datetime import timedelta
import json

# Import models from other apps
from accounts.models import UserProfile
from useractivity.models import Post, Comment, PostLike, Activity, Bookmark
from friendship.models import Friendship, FriendshipStatus, ProfileLike
from chat.models import ChatConversation
from useractivity.forms import PostForm, CommentForm


class DashboardView(LoginRequiredMixin, TemplateView):
    """Clean dashboard that aggregates data from other apps"""
    template_name = 'dashboard/index.html'
    
    def get(self, request, *args, **kwargs):
        try:
            profile = request.user.userprofile
        except UserProfile.DoesNotExist:
            messages.warning(request, "Please complete your profile first.")
            return redirect('accounts:profile_edit')
        
        return super().get(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        try:
            profile = user.userprofile
        except UserProfile.DoesNotExist:
            profile = None
        
        # Get dashboard data without caching complex objects
        dashboard_data = self._get_dashboard_data(user)
        
        context.update({
            'profile': profile,
            **dashboard_data
        })
        
        return context
    
    def _get_dashboard_data(self, user):
        """Aggregate all dashboard data from different apps without caching complex objects"""
        data = {}
        
        # Timeline Posts (get fresh data)
        data.update(self._get_timeline_data(user))
        
        # Sidebar Data (cache only simple values, not complex objects)
        data.update(self._get_left_sidebar_data(user))
        data.update(self._get_right_sidebar_data(user))
        
        # Forms (fresh instances)
        data.update({
            'post_form': PostForm(),
            'comment_form': CommentForm(),
        })
        
        return data
    
    def _get_timeline_data(self, user):
        """Get timeline posts from user and friends without caching"""
        # Get friend IDs
        friends = Friendship.get_friends(user)
        friend_ids = [f.id for f in friends]
        
        # Get posts from user and friends (last 24 hours only)
        twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
        
        posts = Post.objects.filter(
            Q(user=user) | Q(user_id__in=friend_ids),
            created_at__gte=twenty_four_hours_ago,
            is_active=True
        ).select_related(
            'user__userprofile'
        ).prefetch_related(
            Prefetch('comments', queryset=Comment.objects.select_related('user__userprofile')[:5]),
            Prefetch('likes', queryset=PostLike.objects.select_related('user')),
        ).annotate(
            like_count=Count('likes', distinct=True),
            comment_count=Count('comments', distinct=True)
        ).order_by('-created_at')[:20]
        
        # Mark user interactions
        user_like_ids = set(
            PostLike.objects.filter(
                user=user,
                post_id__in=[post.id for post in posts]
            ).values_list('post_id', flat=True)
        )
        
        user_bookmark_ids = set(
            Bookmark.objects.filter(
                user=user,
                post_id__in=[post.id for post in posts]
            ).values_list('post_id', flat=True)
        )
        
        for post in posts:
            post.user_liked = post.id in user_like_ids
            post.user_bookmarked = post.id in user_bookmark_ids
        
        return {
            'posts': posts,
            'friends_count': len(friend_ids),
        }
    
    def _get_left_sidebar_data(self, user):
        """Get left sidebar data with caching for simple values only"""
        cache_key = f"left_sidebar_simple_{user.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        try:
            profile = user.userprofile
            
            # Profile completion
            profile_completion = profile.profile_completion_percentage
            
            # Unread messages
            unread_messages = ChatConversation.objects.filter(
                participants=user,
                messages__is_read=False
            ).exclude(
                messages__sender=user
            ).count()
            
            # Received likes (not mutual)
            received_likes = ProfileLike.objects.filter(
                liked=user,
                is_mutual=False
            ).count()
            
            # Mutual matches
            mutual_matches = ProfileLike.objects.filter(
                (Q(liker=user) | Q(liked=user)) &
                Q(is_mutual=True)
            ).count()
            
            # Friend requests
            friend_requests = Friendship.objects.filter(
                user_b=user,
                status=FriendshipStatus.PENDING_SENDER
            ).count()
            
            # Profile views (last 24 hours)
            profile_views = Activity.objects.filter(
                target_user=user,
                activity_type='profile_view',
                created_at__gte=timezone.now() - timedelta(days=1)
            ).count()
            
            # For notifications, get simple data that can be pickled
            notifications_data = []
            notifications = Activity.objects.filter(
                Q(user=user) | Q(target_user=user),
                created_at__gte=timezone.now() - timedelta(hours=24)
            ).select_related(
                'user__userprofile',
                'target_user__userprofile'
            ).order_by('-created_at')[:5]
            
            for notification in notifications:
                notifications_data.append({
                    'id': notification.id,
                    'activity_type': notification.activity_type,
                    'activity_display': notification.get_activity_type_display(),
                    'created_at': notification.created_at.isoformat(),
                    'user_username': notification.user.username if notification.user else None,
                    'target_username': notification.target_user.username if notification.target_user else None,
                })
            
            result = {
                'profile_completion': profile_completion,
                'unread_messages': unread_messages,
                'received_likes': received_likes,
                'mutual_matches': mutual_matches,
                'friend_requests': friend_requests,
                'notifications_data': notifications_data,  # Simple dict, not QuerySet
                'profile_views': profile_views,
            }
            
            # Cache for 1 minute (simple data only)
            cache.set(cache_key, result, 60)
            
            return result
            
        except UserProfile.DoesNotExist:
            return {}
    
    def _get_right_sidebar_data(self, user):
        """Get right sidebar widgets data with caching for simple values only"""
        cache_key = f"right_sidebar_simple_{user.id}"
        cached = cache.get(cache_key)
        
        if cached is not None:
            return cached
        
        data = {}
        
        try:
            profile = user.userprofile
            
            # Convert QuerySets to simple dicts that can be pickled
            
            # Suggested Matches
            if profile.gender:
                opposite_gender = 'F' if profile.gender == 'M' else 'M'
                suggested_matches_qs = UserProfile.objects.filter(
                    gender=opposite_gender,
                    is_visible=True,
                    approved=True,
                    completed=True
                ).exclude(user=user).select_related('user')[:5]
                
                suggested_matches = []
                for match in suggested_matches_qs:
                    suggested_matches.append({
                        'id': match.user.id,
                        'username': match.user.username,
                        'age': match.age if match.show_age else None,
                        'city': match.city if match.show_location else None,
                        'country': match.country if match.show_location else None,
                        'profile_pic_url': match.profile_pic.url if match.profile_pic else None,
                    })
                data['suggested_matches'] = suggested_matches
            
            # People Nearby
            if profile.city:
                people_nearby_qs = UserProfile.objects.filter(
                    city=profile.city,
                    is_visible=True,
                    approved=True,
                    completed=True
                ).exclude(user=user).select_related('user')[:5]
                
                people_nearby = []
                for person in people_nearby_qs:
                    people_nearby.append({
                        'id': person.user.id,
                        'username': person.user.username,
                        'age': person.age if person.show_age else None,
                        'city': person.city,
                        'profile_pic_url': person.profile_pic.url if person.profile_pic else None,
                    })
                data['people_nearby'] = people_nearby
            
            # Recent Users (last 7 days)
            week_ago = timezone.now() - timedelta(days=7)
            recent_users_qs = UserProfile.objects.filter(
                is_visible=True,
                approved=True,
                created_at__gte=week_ago
            ).exclude(user=user).select_related('user').order_by('-created_at')[:5]
            
            recent_users = []
            for recent_user in recent_users_qs:
                recent_users.append({
                    'id': recent_user.user.id,
                    'username': recent_user.user.username,
                    'created_at': recent_user.created_at.isoformat(),
                    'profile_pic_url': recent_user.profile_pic.url if recent_user.profile_pic else None,
                })
            data['recent_users'] = recent_users
            
            # Cache for 2 minutes (simple data only)
            cache.set(cache_key, data, 120)
            
        except UserProfile.DoesNotExist:
            pass
        
        return data
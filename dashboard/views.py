from asyncio.log import logger
import traceback

from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.db.models import Q, Count, Prefetch
from django.utils import timezone
from django.core.cache import cache
from datetime import timedelta

# Import models
from accounts.models import UserProfile, ActivityLog
from useractivity.models import Post, Comment, PostLike, Activity, Bookmark
from friendship.models import Friendship, FriendshipStatus, ProfileLike
from chat.models import ChatConversation
from useractivity.forms import PostForm, CommentForm
import logging

logger = logging.getLogger(__name__)

class DashboardView(LoginRequiredMixin, TemplateView):
    """Clean dashboard that aggregates data from other apps"""
    template_name = "dashboard/index.html"

    def get(self, request, *args, **kwargs):
        if not hasattr(request.user, "userprofile"):
            messages.warning(request, "Please complete your profile first.")
            return redirect("accounts:profile_edit")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        profile = getattr(user, "userprofile", None)

        if profile:
            context['total_matches'] = profile.get_matches_count(threshold=50)
        else:
            context['total_matches'] = 0
        
        # FIX: Add new_matches_today count
        context['new_matches_today'] = UserProfile.new_matches_today().count()

        dashboard_data = self._get_dashboard_data(user)

        context.update({
            "profile": profile,
            **dashboard_data,
        })
        
        # FIX: Add suggested_people to context
        context["suggested_people"] = self._get_people_you_may_like(user)

        # Friendship counts
        context['total_friends'] = len(Friendship.get_friends(user))
        context['pending_sent'] = Friendship.objects.filter(
            (Q(user_a=user, status=FriendshipStatus.PENDING_SENDER) |
             Q(user_b=user, status=FriendshipStatus.PENDING_RECEIVER))
        ).count()
        context['pending_received'] = Friendship.objects.filter(
            (Q(user_a=user, status=FriendshipStatus.PENDING_RECEIVER) |
             Q(user_b=user, status=FriendshipStatus.PENDING_SENDER))
        ).count()
        
        # DEBUG: Print what's in recent_posts
        recent_posts = context.get('recent_posts', [])
        print(f"DEBUG - recent_posts count: {len(recent_posts)}")
        if recent_posts:
            print(f"DEBUG - recent_posts IDs: {[p.id for p in recent_posts]}")
        else:
            print("DEBUG - recent_posts is EMPTY")
        
        return context

    # ------------------------------------------------------------------
    # Main aggregator
    # ------------------------------------------------------------------

    def _get_dashboard_data(self, user):
        data = {}

        data.update(self._get_timeline_data(user))
        data.update(self._get_left_sidebar_data(user))
        data.update(self._get_right_sidebar_data(user))
        
        # Add people nearby data
        data['people_nearby'] = self._get_people_nearby(user)
        
        # Add recent posts for timeline
        data['recent_posts'] = self._get_recent_posts(user) 

        data.update({
            "post_form": PostForm(),
            "comment_form": CommentForm(),
        })

        return data

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------
    def _get_recent_posts(self, user):
        """
        Get 5 most recent posts from user and friends for dashboard
        """
        try:
            # Get user's friends
            friends = Friendship.get_friends(user)
            friend_ids = [f.id for f in friends]
            
            # Build queryset with ALL operations BEFORE slicing
            posts = (
                Post.objects.filter(
                    Q(user=user) | Q(user_id__in=friend_ids),
                    is_active=True
                )
                .select_related('user__userprofile')
                .prefetch_related(
                    Prefetch(
                        'comments',
                        queryset=Comment.objects.select_related('user__userprofile').order_by('-created_at')
                    )
                )
                .annotate(
                    post_likes_count=Count('likes', distinct=True),
                    post_comments_count=Count('comments', distinct=True)
                )
                .order_by('-created_at')
            )
            
            # NOW slice after all queryset operations
            posts = posts[:5]
            
            # Convert to list
            posts_list = list(posts)
            
            # Get user likes for these posts
            if posts_list:
                post_ids = [p.id for p in posts_list]
                user_likes = set(
                    PostLike.objects.filter(
                        user=user,
                        post_id__in=post_ids
                    ).values_list('post_id', flat=True)
                )
                
                for post in posts_list:
                    post.user_liked = post.id in user_likes
            
            return posts_list
            
        except Exception as e:
            print(f"Error in _get_recent_posts: {e}")
            import traceback
            traceback.print_exc()
            return []
    

    def _get_timeline_data(self, user):
        cache_key = f"timeline_posts_{user.id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        friends = Friendship.get_friends(user)
        friend_ids = [f.id for f in friends]

        # Build the queryset with all filters
        posts_qs = (
            Post.objects.filter(
                Q(user=user) | Q(user_id__in=friend_ids),
                is_active=True,
            )
            .select_related("user__userprofile")
            .prefetch_related(
                Prefetch(
                    "comments",
                    queryset=Comment.objects.select_related(
                        "user__userprofile"
                    ).only(
                        "id", "content", "created_at", "user_id"
                    ).order_by("-created_at"),   # ✅ no slice here
                ),
            )
            .annotate(
                like_count=Count("likes", distinct=True),
                comment_count=Count("comments", distinct=True),
            )
            .only(
                "id", "content", "image", "created_at", "user_id"
            )
            .order_by("-created_at")
        )

        # Get 20 most recent posts
        posts = list(posts_qs[:20])
        
        # Get post IDs
        post_ids = [p.id for p in posts] if posts else []
        
        # Get user interactions
        user_likes = set()
        user_bookmarks = set()

        if post_ids:
            user_likes = set(
                PostLike.objects.filter(
                    user=user, post_id__in=post_ids
                ).values_list("post_id", flat=True)
            )
            user_bookmarks = set(
                Bookmark.objects.filter(
                    user=user, post_id__in=post_ids
                ).values_list("post_id", flat=True)
            )

        # Mark user interactions
        for post in posts:
            post.user_liked = post.id in user_likes
            post.user_bookmarked = post.id in user_bookmarks
            # Add these for template compatibility
            post.likes_count = getattr(post, 'like_count', 0)
            post.comments_count = getattr(post, 'comment_count', 0)

        result = {
            "posts": posts,
            "friends_count": len(friend_ids),
        }

        cache.set(cache_key, result, 60)
        return result
    # ------------------------------------------------------------------
    # Left sidebar
    # ------------------------------------------------------------------

    def _get_left_sidebar_data(self, user):
        cache_key = f"left_sidebar_simple_{user.id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        try:
            profile = user.userprofile

            # FIX: Don't use annotation that conflicts with model field
            # Instead, get unread messages count directly
            unread_messages = ChatConversation.objects.filter(
                participants=user,
                messages__is_read=False
            ).exclude(
                messages__sender=user
            ).count()

            total_matches = profile.get_matches_count(threshold=50)

            result = {
                "profile_completion": profile.profile_completion_percentage,
                "unread_messages": unread_messages,
                "total_matches": total_matches,
                "received_likes": ProfileLike.objects.filter(
                    liked=user, is_mutual=False
                ).count(),
                "mutual_matches": ProfileLike.objects.filter(
                    Q(liker=user) | Q(liked=user),
                    is_mutual=True,
                ).count(),
                "friend_requests": Friendship.objects.filter(
                    user_b=user,
                    status=FriendshipStatus.PENDING_SENDER,
                ).count(),
                "profile_views": ActivityLog.objects.filter(
                    target_user=user,
                    activity_type="profile_view",
                    created_at__gte=timezone.now() - timedelta(days=1),
                ).count(),
                "notifications_data": self._get_notifications(user),
            }

            cache.set(cache_key, result, 60)
            return result

        except UserProfile.DoesNotExist:
            return {}
    

    def _get_notifications(self, user):
        notifications = Activity.objects.filter(
            Q(user=user) | Q(target_user=user),
            created_at__gte=timezone.now() - timedelta(hours=24),
        ).select_related(
            "user__userprofile",
            "target_user__userprofile",
        ).order_by("-created_at")[:5]

        data = []
        for n in notifications:
            data.append({
                "id": n.id,
                "type": n.activity_type,
                "label": n.get_activity_type_display(),
                "created_at": n.created_at.isoformat(),
                "user": n.user.username if n.user else None,
                "target": n.target_user.username if n.target_user else None,
            })
        return data


    # ------------------------------------------------------------------
    # Right sidebar
    # ------------------------------------------------------------------

    def _get_right_sidebar_data(self, user):
        cache_key = f"right_sidebar_simple_{user.id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        data = {}

        try:
            profile = user.userprofile

            # FIX: Optimize suggested matches query
            if profile.gender:
                opposite_gender = "F" if profile.gender == "M" else "M"
                qs = UserProfile.objects.filter(
                    gender=opposite_gender,
                    is_visible=True,
                    approved=True,
                ).exclude(user=user).select_related("user")[:5]

                data["suggested_matches"] = [
                    {
                        "id": p.user.id,
                        "username": p.user.username,
                        "age": p.age if p.show_age else None,
                        "city": p.city if p.show_location else None,
                        "country": p.country if p.show_location else None,
                        "profile_pic_url": p.profile_pic.url if p.profile_pic else None,
                    }
                    for p in qs
                ]

            # FIX: Optimize recent users query
            week_ago = timezone.now() - timedelta(days=7)
            qs = UserProfile.objects.filter(
                is_visible=True,
                approved=True,
                created_at__gte=week_ago,
            ).exclude(user=user).select_related("user").order_by("-created_at")[:5]

            data["recent_users"] = [
                {
                    "id": p.user.id,
                    "username": p.user.username,
                    "created_at": p.created_at,
                    "profile_pic_url": p.profile_pic.url if p.profile_pic else None,
                }
                for p in qs
            ]

            cache.set(cache_key, data, 120)

        except UserProfile.DoesNotExist:
            pass

        return data
    
    def _get_people_you_may_like(self, user):
        """Get personalized people suggestions based on compatibility"""
        try:
            profile = user.userprofile
            
            # Check cache first for the entire suggestion list
            cache_key = f"people_you_may_like_{user.id}"
            cached_results = cache.get(cache_key)
            if cached_results:
                return cached_results
            
            # Get user's preferences
            looking_for = profile.get_preference('looking_for', '')
            
            # Build base query
            base_filters = {
                'is_visible': True,
                'approved': True,
            }
            
            if looking_for and looking_for != 'B':
                base_filters['gender'] = looking_for
            
            # Get potential matches
            qs = (
                UserProfile.objects
                .filter(**base_filters)
                .exclude(user=user)
                .select_related("user")
                .only(
                    "id", "user_id", "age", "gender", "city", "country", 
                    "sect", "education", "practice_level", "profile_pic",
                    "show_age", "show_location", "show_sect", "show_education",
                    "show_practice_level", "bio", "preferences"
                )
            )
            
            # Get all profiles (limit to 200 for performance)
            profiles = list(qs[:200])
            
            # Batch calculate compatibilities
            results = []
            for p in profiles:
                compat_cache_key = f"compat_{user.id}_{p.user.id}"
                score = cache.get(compat_cache_key)
                
                if score is None:
                    score = profile.calculate_compatibility(p)
                    cache.set(compat_cache_key, score, 3600)  # Cache for 1 hour
                
                # You can adjust this threshold
                if score >= 20:  # Only show profiles with at least 20% compatibility
                    results.append({
                        "profile": p,
                        "user": p.user,
                        "compatibility": round(score, 1),
                        # Add these for template use
                        "is_same_city": (p.city and profile.city and 
                                        p.city.lower() == profile.city.lower()),
                        "is_same_country": (p.country and profile.country and 
                                        p.country.lower() == profile.country.lower()),
                        "age_display": p.age if p.show_age else None,
                        "location_display": self._get_location_display(p, profile),
                    })
            
            # Sort by compatibility (highest first)
            results.sort(key=lambda x: x["compatibility"], reverse=True)
            
            # Take top 12, but we'll return 8
            top_results = results[:12]
            
            # Cache the final results for 30 minutes
            cache.set(cache_key, top_results[:8], 1800)
            
            return top_results[:8]
            
        except UserProfile.DoesNotExist:
            return []
        except Exception as e:
            logger.error(f"Error in _get_people_you_may_like: {e}")
            return []

    def _get_location_display(self, profile, user_profile):
        """Helper method to format location display"""
        if not profile.show_location:
            return "Location hidden"
        
        parts = []
        if profile.city:
            parts.append(profile.city)
        if profile.country:
            parts.append(profile.country)
        
        return ", ".join(parts) if parts else "Location not set"
    
    def _get_people_nearby(self, user):
        """
        Get people nearby based on user's location with opposite gender filter
        """
        try:
            profile = user.userprofile
            
            # If user doesn't have location or gender, return empty list
            if not profile.city and not profile.country:
                return []
            
            # Determine opposite gender
            opposite_gender = None
            if profile.gender == 'M':
                opposite_gender = 'F'
            elif profile.gender == 'F':
                opposite_gender = 'M'
            else:
                # If gender is 'O' (Other) or 'N' (Prefer not to say), 
                # show all genders but prioritize opposite biological gender
                opposite_gender = None
            
            # Base queryset with gender filter
            nearby_queryset = UserProfile.objects.filter(
                is_visible=True,
                approved=True,
            ).exclude(user=user).select_related('user')
            
            # Apply opposite gender filter if available
            if opposite_gender:
                nearby_queryset = nearby_queryset.filter(gender=opposite_gender)
            
            # If no profiles found with opposite gender, try without gender filter
            # This ensures we always show some profiles
            if not nearby_queryset.exists():
                nearby_queryset = UserProfile.objects.filter(
                    is_visible=True,
                    approved=True,
                ).exclude(user=user).select_related('user')
            
            # Filter by location priority
            same_city_profiles = []
            same_country_profiles = []
            other_profiles = []
            
            # First, get people in same city
            if profile.city:
                same_city_profiles = list(nearby_queryset.filter(
                    city__iexact=profile.city
                )[:4])  # Limit to 4 for dashboard
            
            # Then, get people in same country (excluding same city)
            if profile.country:
                country_qs = nearby_queryset.filter(
                    country__iexact=profile.country
                )
                if profile.city:
                    country_qs = country_qs.exclude(city__iexact=profile.city)
                same_country_profiles = list(country_qs[:4])
            
            # Combine with priority: same city first, then same country
            nearby_profiles = same_city_profiles + same_country_profiles
            
            # If we still need more, add random profiles
            if len(nearby_profiles) < 4:
                existing_ids = [p.user.id for p in nearby_profiles]
                other_profiles = list(
                    nearby_queryset.exclude(user_id__in=existing_ids)[:4 - len(nearby_profiles)]
                )
                nearby_profiles.extend(other_profiles)
            
            # Enhance with location indicators
            enhanced = []
            for p in nearby_profiles[:4]:  # Ensure max 4
                is_same_city = (p.city and profile.city and 
                            p.city.lower() == profile.city.lower())
                is_same_country = (p.country and profile.country and 
                                p.country.lower() == profile.country.lower() and not is_same_city)
                
                # Calculate distance type
                if is_same_city:
                    distance_text = 'Same City'
                    distance_icon = '📍'
                elif is_same_country:
                    distance_text = 'Same Country'
                    distance_icon = '🌍'
                else:
                    distance_text = 'Other'
                    distance_icon = '🌎'
                
                # Check if gender matches opposite (for display)
                is_opposite_gender = (p.gender == opposite_gender) if opposite_gender else True
                
                enhanced.append({
                    'profile': p,
                    'user': p.user,
                    'is_same_city': is_same_city,
                    'is_same_country': is_same_country,
                    'distance_text': distance_text,
                    'distance_icon': distance_icon,
                    'is_opposite_gender': is_opposite_gender,
                    'gender_display': p.get_gender_display() if p.gender else 'Not specified',
                })
            
            return enhanced
            
        except UserProfile.DoesNotExist:
            return []
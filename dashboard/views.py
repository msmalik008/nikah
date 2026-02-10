from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.db.models import Q, Count, Prefetch
from django.utils import timezone
from django.core.cache import cache
from datetime import timedelta

# Import models
from accounts.models import UserProfile
from useractivity.models import Post, Comment, PostLike, Activity, Bookmark
from friendship.models import Friendship, FriendshipStatus, ProfileLike
from chat.models import ChatConversation
from useractivity.forms import PostForm, CommentForm


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

        dashboard_data = self._get_dashboard_data(user)

        context.update({
            "profile": profile,
            **dashboard_data,
        })
        return context

    # ------------------------------------------------------------------
    # Main aggregator
    # ------------------------------------------------------------------

    def _get_dashboard_data(self, user):
        data = {}

        data.update(self._get_timeline_data(user))
        data.update(self._get_left_sidebar_data(user))
        data.update(self._get_right_sidebar_data(user))

        data.update({
            "post_form": PostForm(),
            "comment_form": CommentForm(),
        })

        return data

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def _get_timeline_data(self, user):
        cache_key = f"timeline_posts_{user.id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        friends = Friendship.get_friends(user)
        friend_ids = [f.id for f in friends]

        since = timezone.now() - timedelta(hours=24)

        posts_qs = (
            Post.objects.filter(
                Q(user=user) | Q(user_id__in=friend_ids),
                created_at__gte=since,
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
                    ).order_by("-created_at"),
                ),
                Prefetch(
                    "likes",
                    queryset=PostLike.objects.only("id", "user_id"),
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

        posts = list(posts_qs[:20])  # slice ONLY here

        post_ids = [p.id for p in posts]

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

        for post in posts:
            post.user_liked = post.id in user_likes
            post.user_bookmarked = post.id in user_bookmarks

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

            unread_messages = ChatConversation.objects.filter(
                participants=user,
                messages__is_read=False,
            ).exclude(
                messages__sender=user
            ).count()

            result = {
                "profile_completion": profile.profile_completion_percentage,
                "unread_messages": unread_messages,
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
                "profile_views": Activity.objects.filter(
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

            if profile.city:
                qs = UserProfile.objects.filter(
                    city=profile.city,
                    is_visible=True,
                    approved=True,
                ).exclude(user=user).select_related("user")[:5]

                data["people_nearby"] = [
                    {
                        "id": p.user.id,
                        "username": p.user.username,
                        "age": p.age if p.show_age else None,
                        "city": p.city,
                        "profile_pic_url": p.profile_pic.url if p.profile_pic else None,
                    }
                    for p in qs
                ]

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
                    "created_at": p.created_at.isoformat(),
                    "profile_pic_url": p.profile_pic.url if p.profile_pic else None,
                }
                for p in qs
            ]

            cache.set(cache_key, data, 120)

        except UserProfile.DoesNotExist:
            pass

        return data

from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, CreateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Count, Prefetch
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.contrib import messages
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from datetime import timedelta
from .models import Post, Comment, PostLike, CommentLike, Share, Bookmark, Activity
from .forms import PostForm, CommentForm, ShareForm
from friendship.models import Friendship
import json

import logging
logger = logging.getLogger(__name__)


# useractivity/views.py - FIXED TimelineView

class TimelineView(LoginRequiredMixin, View):
    """Main timeline view"""
    template_name = "useractivity/timeline.html"

    def get(self, request):
        user = request.user
        logger.info(f"TimelineView accessed by {user.username}")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return self._get_ajax_posts(request, user)

        return self._get_full_page(request, user)

    # --------------------------------------------------
    # Full page timeline
    # --------------------------------------------------

    def _get_full_page(self, request, user):
        friends = Friendship.get_friends(user)
        friend_ids = [f.id for f in friends]

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
                    ).order_by("-created_at"),
                ),
                Prefetch(
                    "likes",
                    queryset=PostLike.objects.only("id", "user_id"),
                ),
            )
            .annotate(
                likes_total=Count("likes", distinct=True),
                comments_total=Count("comments", distinct=True),
            )
            .order_by("-created_at")
        )


        paginator = Paginator(posts_qs, 20)
        page_number = request.GET.get("page", 1)

        try:
            posts_page = paginator.page(page_number)
        except PageNotAnInteger:
            posts_page = paginator.page(1)
        except EmptyPage:
            posts_page = paginator.page(paginator.num_pages)

        # User interactions (bulk)
        post_ids = [p.id for p in posts_page]

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

        for post in posts_page:
            post.user_liked = post.id in user_likes
            post.user_bookmarked = post.id in user_bookmarks

        context = {
            "posts": posts_page,
            "post_form": PostForm(),
            "comment_form": CommentForm(),
            "friends_count": len(friend_ids),
            "is_paginated": paginator.num_pages > 1,
            "page_obj": posts_page,
            "paginator": paginator,
        }

        logger.info(f"Rendering timeline with {posts_page.paginator.count} posts")
        return render(request, self.template_name, context)

    # --------------------------------------------------
    # AJAX posts (infinite scroll / refresh)
    # --------------------------------------------------

    def _get_ajax_posts(self, request, user):
        friends = Friendship.get_friends(user)
        friend_ids = [f.id for f in friends]

        posts = (
            Post.objects.filter(
                Q(user=user) | Q(user_id__in=friend_ids),
                is_active=True,
            )
            .select_related("user__userprofile")
            .annotate(
                likes_count=Count("likes", distinct=True),
                comments_count=Count("comments", distinct=True),
            )
            .order_by("-created_at")[:20]
        )

        posts_data = []
        for post in posts:
            posts_data.append({
                "id": post.id,
                "content": post.content,
                "image": post.image.url if post.image else None,
                "created_at": post.created_at.strftime("%b %d, %Y %I:%M %p"),
                "user": {
                    "username": post.user.username,
                    "profile_pic": (
                        post.user.userprofile.profile_pic.url
                        if post.user.userprofile.profile_pic
                        else None
                    ),
                },
                "likes_count": post.likes_count,
                "comments_count": post.comments_count,
            })

        return JsonResponse({
            "success": True,
            "posts": posts_data,
            "count": len(posts_data),
        })


class LikePostView(LoginRequiredMixin, View):
    """Like or unlike a post"""
    
    def post(self, request, post_id):
        post = get_object_or_404(Post, id=post_id)
        
        like, created = PostLike.objects.get_or_create(
            user=request.user,
            post=post
        )
        
        if not created:
            like.delete()
            action = 'unliked'
            # Remove activity if exists
            Activity.objects.filter(
                user=request.user,
                activity_type='post_liked',
                post=post
            ).delete()
        else:
            action = 'liked'
            # Create activity
            Activity.objects.create(
                user=request.user,
                activity_type='post_liked',
                target_user=post.user,
                post=post
            )
        
        post.update_counts()
        
        return JsonResponse({
            'success': True,
            'action': action,
            'likes_count': post.likes_count
        })


@login_required
@require_POST
def toggle_post_like(request, post_id):
    """Toggle like on a post"""
    post = get_object_or_404(Post, id=post_id)
    
    # Check if user already liked this post
    existing_like = PostLike.objects.filter(user=request.user, post=post).first()
    
    if existing_like:
        # Unlike - remove the like
        existing_like.delete()
        liked = False
    else:
        # Like - create new like
        PostLike.objects.create(user=request.user, post=post)
        liked = True
    
    # Get updated like count from database
    like_count = post.likes.count()
    
    return JsonResponse({
        'success': True,
        'liked': liked,
        'like_count': like_count
    })

class CommentPostView(LoginRequiredMixin, View):
    """Add comment to a post"""
    
    def post(self, request, post_id):
        post = get_object_or_404(Post, id=post_id)
        form = CommentForm(request.POST)
        
        if form.is_valid():
            comment = form.save(commit=False)
            comment.user = request.user
            comment.post = post
            comment.save()
            
            # Update post comment count
            post.update_counts()
            
            # Create activity
            Activity.objects.create(
                user=request.user,
                activity_type='comment_created',
                target_user=post.user,
                post=post,
                comment=comment
            )
            
            return JsonResponse({
                'success': True,
                'comment_id': comment.id,
                'comments_count': post.comments_count
            })
        
        return JsonResponse({
            'success': False,
            'errors': form.errors
        })


# posts/views.py
@login_required
@require_POST
def add_comment(request):
    """Add a comment to a post"""
    post_id = request.POST.get('post_id')
    content = request.POST.get('content', '').strip()
    
    if not content:
        return JsonResponse({'success': False, 'error': 'Comment cannot be empty'})
    
    post = get_object_or_404(Post, id=post_id)
    
    # Create comment
    comment = Comment.objects.create(
        user=request.user,
        post=post,
        content=content
    )
    
    # Return comment data
    return JsonResponse({
        'success': True,
        'comment': {
            'id': comment.id,
            'user': {
                'username': comment.user.username,
                'profile_pic': comment.user.userprofile.profile_pic.url if hasattr(comment.user, 'userprofile') and comment.user.userprofile.profile_pic else None
            },
            'content': comment.content,
            'created_at': comment.created_at.isoformat(),
            'is_owner': comment.user == request.user
        }
    })

class LikeCommentView(LoginRequiredMixin, View):
    """Like or unlike a comment"""
    
    def post(self, request, comment_id):
        comment = get_object_or_404(Comment, id=comment_id)
        
        like, created = CommentLike.objects.get_or_create(
            user=request.user,
            comment=comment
        )
        
        if not created:
            like.delete()
            action = 'unliked'
        else:
            action = 'liked'
            # Create activity
            Activity.objects.create(
                user=request.user,
                activity_type='comment_liked',
                target_user=comment.user,
                comment=comment,
                post=comment.post
            )
        
        # Update comment likes count
        comment.likes_count = comment.likes.count()
        comment.save(update_fields=['likes_count'])
        
        return JsonResponse({
            'success': True,
            'action': action,
            'likes_count': comment.likes_count
        })

@login_required
@require_POST
def delete_comment(request, comment_id):
    """Delete a comment"""
    comment = get_object_or_404(Comment, id=comment_id)
    
    # Check if user owns the comment
    if comment.user != request.user:
        return JsonResponse({'success': False, 'error': 'You can only delete your own comments'})
    
    comment.delete()
    
    return JsonResponse({
        'success': True,
        'message': 'Comment deleted'
    })



class SharePostView(LoginRequiredMixin, View):
    """Share a post"""
    
    def post(self, request, post_id):
        post = get_object_or_404(Post, id=post_id)
        
        share, created = Share.objects.get_or_create(
            user=request.user,
            post=post
        )
        
        if created:
            # Create activity
            Activity.objects.create(
                user=request.user,
                activity_type='post_shared',
                target_user=post.user,
                post=post
            )
        
        return JsonResponse({
            'success': True,
            'created': created
        })


class BookmarkPostView(LoginRequiredMixin, View):
    """Bookmark or remove bookmark from a post"""
    
    def post(self, request, post_id):
        post = get_object_or_404(Post, id=post_id)
        
        bookmark, created = Bookmark.objects.get_or_create(
            user=request.user,
            post=post
        )
        
        if not created:
            bookmark.delete()
            action = 'removed'
        else:
            action = 'added'
            # Create activity
            Activity.objects.create(
                user=request.user,
                activity_type='post_bookmarked',
                post=post
            )
        
        return JsonResponse({
            'success': True,
            'action': action
        })


class DeletePostView(LoginRequiredMixin, DeleteView):
    """Delete a post"""
    model = Post
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        
        # Check ownership
        if self.object.user != request.user:
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            })
        
        post_id = self.object.id
        self.object.delete()
        
        return JsonResponse({
            'success': True,
            'post_id': post_id
        })


class ActivityStreamView(LoginRequiredMixin, ListView):
    """User activity stream"""
    model = Activity
    template_name = 'useractivity/activity_stream.html'
    context_object_name = 'activities'
    paginate_by = 30
    
    def get_queryset(self):
        user = self.request.user
        
        # Get activities involving the user
        queryset = Activity.objects.filter(
            Q(user=user) | Q(target_user=user)
        ).select_related(
            'user__userprofile',
            'target_user__userprofile',
            'post',
            'comment'
        ).order_by('-created_at')
        
        # Mark as read when viewed
        queryset.update(is_read=True)
        
        return queryset


class UserPostsView(LoginRequiredMixin, ListView):
    """View a user's posts"""
    model = Post
    template_name = 'useractivity/user_posts.html'
    context_object_name = 'posts'
    paginate_by = 20
    
    def get_queryset(self):
        user_id = self.kwargs.get('user_id')
        user = get_object_or_404(User, id=user_id)
        
        return Post.objects.filter(
            user=user,
            is_active=True
        ).select_related('user__userprofile').prefetch_related(
            'comments', 'likes'
        ).order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = self.kwargs.get('user_id')
        context['profile_user'] = get_object_or_404(User, id=user_id)
        return context


@login_required
@require_http_methods(["GET"])
def get_post_comments(request, post_id):
    """Get comments for a post (AJAX endpoint)"""
    try:
        post = Post.objects.get(id=post_id)
        comments = post.comments.select_related('user__userprofile').order_by('-created_at')[:50]
        
        comments_data = []
        for comment in comments:
            comments_data.append({
                'id': comment.id,
                'user': {
                    'id': comment.user.id,
                    'username': comment.user.username,
                    'profile_pic': comment.user.userprofile.profile_pic.url if comment.user.userprofile.profile_pic else None,
                },
                'content': comment.content,
                'created_at': comment.created_at.strftime('%b %d, %Y %I:%M %p'),
                'likes_count': comment.likes_count,
            })
        
        return JsonResponse({
            'success': True,
            'comments': comments_data,
        })
    except Post.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Post not found',
        })


@login_required
@require_http_methods(["GET"])
def get_post_likes(request, post_id):
    """Get likes for a post (AJAX endpoint)"""
    try:
        post = Post.objects.get(id=post_id)
        likes = post.likes.select_related('user__userprofile')[:50]
        
        likes_data = []
        for like in likes:
            likes_data.append({
                'id': like.user.id,
                'username': like.user.username,
                'profile_pic': like.user.userprofile.profile_pic.url if like.user.userprofile.profile_pic else None,
                'liked_at': like.created_at.strftime('%b %d, %Y %I:%M %p'),
            })
        
        return JsonResponse({
            'success': True,
            'likes': likes_data,
            'total_likes': post.likes_count,
        })
    except Post.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Post not found',
        })



class RecentActivityAPIView(LoginRequiredMixin, View):
    """API endpoint for recent activity"""
    
    def get(self, request):
        from accounts.models import ActivityLog
        
        activities = ActivityLog.objects.filter(
            Q(user=request.user) | Q(target_user=request.user)
        ).select_related('user__userprofile', 'target_user__userprofile').order_by('-created_at')[:5]
        
        activities_data = []
        for activity in activities:
            activities_data.append({
                'id': activity.id,
                'type': activity.get_activity_type_display(),
                'user': activity.user.username,
                'target_user': activity.target_user.username if activity.target_user else None,
                'created_at': activity.created_at.strftime('%I:%M %p'),
                'description': self._get_activity_description(activity)
            })
        
        return JsonResponse({
            'success': True,
            'activities': activities_data
        })
    
    def _get_activity_description(self, activity):
        """Generate human-readable activity description"""
        if activity.target_user:
            return f"{activity.user.username} {activity.get_activity_type_display().lower()} {activity.target_user.username}"
        return f"{activity.user.username} {activity.get_activity_type_display().lower()}"


class PostAPIView(LoginRequiredMixin, View):
    """API endpoint for posts"""
    
    def get(self, request):
        user = request.user
        friends = Friendship.get_friends(user)
        friend_ids = [f.id for f in friends]
        
        posts = Post.objects.filter(
            Q(user=user) | Q(user_id__in=friend_ids),
            is_active=True
        ).select_related('user__userprofile').order_by('-created_at')[:20]
        
        posts_data = []
        for post in posts:
            posts_data.append({
                'id': post.id,
                'content': post.content,
                'image': post.image.url if post.image else None,
                'created_at': post.created_at.strftime('%b %d, %Y %I:%M %p'),
                'user': {
                    'id': post.user.id,
                    'username': post.user.username,
                    'profile_pic': post.user.userprofile.profile_pic.url if post.user.userprofile.profile_pic else '/static/img/default-avatar.png',
                },
                'likes_count': post.likes_count,
                'comments_count': post.comments_count,
                'user_liked': post.likes.filter(user=user).exists(),
                'user_bookmarked': post.bookmarks.filter(user=user).exists(),
            })
        
        return JsonResponse({
            'success': True,
            'posts': posts_data,
            'friends_count': len(friend_ids)
        })


class CreatePostView(LoginRequiredMixin, View):
    """Create post via API"""
    
    def post(self, request):
        form = PostForm(request.POST, request.FILES)
        
        if form.is_valid():
            post = form.save(commit=False)
            post.user = request.user
            post.save()
            
            return JsonResponse({
                'success': True,
                'post_id': post.id,
                'message': 'Post created successfully'
            })
        
        return JsonResponse({
            'success': False,
            'errors': form.errors
        }, status=400)
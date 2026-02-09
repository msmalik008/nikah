from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, CreateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.db.models import Q, Count
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.contrib import messages
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from datetime import timedelta

from .models import Post, Comment, PostLike, CommentLike, Share, Bookmark, Activity
from .forms import PostForm, CommentForm, ShareForm
from friendship.models import Friendship


class TimelineView(LoginRequiredMixin, View):
    """Main timeline view"""
    template_name = 'useractivity/timeline.html'
    
    def get(self, request):
        user = request.user
        
        # Get user's friends
        friends = Friendship.get_friends(user)
        friend_ids = [f.id for f in friends]
        
        # Get posts from user and friends
        posts = Post.objects.filter(
            Q(user=user) | Q(user_id__in=friend_ids),
            is_active=True
        ).select_related(
            'user__userprofile'
        ).prefetch_related(
            'comments__user__userprofile',
            'likes__user',
            'shares__user',
            'bookmarks'
        ).order_by('-created_at')
        
        # Paginate posts
        paginator = Paginator(posts, 20)
        page = request.GET.get('page')
        
        try:
            posts_page = paginator.page(page)
        except PageNotAnInteger:
            posts_page = paginator.page(1)
        except EmptyPage:
            posts_page = paginator.page(paginator.num_pages)
        
        # Mark user interactions
        for post in posts_page:
            post.user_liked = post.likes.filter(user=user).exists()
            post.user_bookmarked = post.bookmarks.filter(user=user).exists()
        
        context = {
            'posts': posts_page,
            'post_form': PostForm(),
            'comment_form': CommentForm(),
            'friends_count': len(friend_ids),
            'is_paginated': paginator.num_pages > 1,
            'page_obj': posts_page,
            'paginator': paginator,
        }
        
        return render(request, self.template_name, context)


class CreatePostView(LoginRequiredMixin, CreateView):
    """Create a new post"""
    model = Post
    form_class = PostForm
    http_method_names = ['post']
    
    def form_valid(self, form):
        post = form.save(commit=False)
        post.user = self.request.user
        post.save()
        
        # Create activity
        Activity.objects.create(
            user=self.request.user,
            activity_type='post_created',
            post=post
        )
        
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'post_id': post.id,
                'message': 'Post created successfully'
            })
        
        messages.success(self.request, 'Post created successfully')
        return redirect('useractivity:timeline')
    
    def form_invalid(self, form):
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'errors': form.errors
            })
        
        messages.error(self.request, 'Error creating post')
        return redirect('useractivity:timeline')


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


class DeleteCommentView(LoginRequiredMixin, View):
    """Delete a comment"""
    
    def delete(self, request, comment_id):
        try:
            comment = Comment.objects.get(id=comment_id)
            
            # Check ownership
            if comment.user != request.user:
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                })
            
            # Get post ID before deletion (for cache clearing)
            post_id = comment.post_id
            comment.delete()
            
            # Update post comment count
            post = Post.objects.get(id=post_id)
            post.update_counts()
            
            return JsonResponse({
                'success': True,
                'comment_id': comment_id,
            })
        except Comment.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Comment not found',
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
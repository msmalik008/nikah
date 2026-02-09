def user_profile(request):
    """Add user profile to context"""
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        return {
            'user_profile': request.user.profile,
            'unread_messages': request.user.received_messages.filter(is_read=False).count(),
        }
    return {}

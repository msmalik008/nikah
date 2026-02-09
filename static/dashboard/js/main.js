// dashboard/static/dashboard/js/main.js
$(document).ready(function() {
    // Auto-dismiss alerts after 5 seconds
    setTimeout(function() {
        $('.alert').alert('close');
    }, 5000);
    
    // Like button handler
    $('.like-btn').click(function(e) {
        e.preventDefault();
        const btn = $(this);
        const profileId = btn.data('profile-id');
        const url = `/dashboard/like/${profileId}/`;
        
        btn.prop('disabled', true);
        
        $.post(url, {}, function(response) {
            if (response.success) {
                btn.html('<i class="fas fa-heart text-danger"></i> Liked');
                if (response.is_mutual) {
                    alert('It\'s a match!');
                }
            } else {
                alert(response.message);
                btn.prop('disabled', false);
            }
        }).fail(function() {
            alert('An error occurred. Please try again.');
            btn.prop('disabled', false);
        });
    });
    
    // Accept friend request handler
    $('.accept-request-btn').click(function(e) {
        e.preventDefault();
        const btn = $(this);
        const requestId = btn.data('request-id');
        const url = `/dashboard/accept-request/${requestId}/`;
        
        btn.prop('disabled', true);
        
        $.post(url, {}, function(response) {
            if (response.success) {
                btn.closest('.request-item').fadeOut();
            } else {
                alert(response.message);
                btn.prop('disabled', false);
            }
        });
    });
    
    // Mark message as read
    $('.message-item').click(function() {
        const messageId = $(this).data('message-id');
        const url = `/dashboard/mark-read/${messageId}/`;
        
        $.post(url, {}, function(response) {
            if (response.success) {
                $(this).removeClass('unread');
            }
        });
    });
    
    // Filter form submission with AJAX
    $('#filter-form').submit(function(e) {
        e.preventDefault();
        const form = $(this);
        const url = form.attr('action') || window.location.pathname;
        const data = form.serialize();
        
        $.get(url, data, function(response) {
            $('#matches-container').html($(response).find('#matches-container').html());
        });
    });
    
    // Refresh notifications count every 30 seconds
    function refreshNotifications() {
        $.get('/dashboard/api/notifications-count/', function(data) {
            if (data.count > 0) {
                $('#notifications-count').text(data.count).show();
            } else {
                $('#notifications-count').hide();
            }
        });
    }
    
    setInterval(refreshNotifications, 30000);
});
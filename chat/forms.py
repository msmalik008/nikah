from django import forms
from .models import *


class MessageForm(forms.Form):
    content = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Type your message here...',
            'maxlength': 1000
        }),
        max_length=1000,
        min_length=1
    )
    
    def __init__(self, *args, **kwargs):
        self.sender = kwargs.pop('sender', None)
        self.receiver = kwargs.pop('receiver', None)
        super().__init__(*args, **kwargs)
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Check if users can message (must be friends or have mutual match)
        from .models import Friendship, Like
        
        # Check if they are friends
        are_friends = Friendship.are_friends(self.sender, self.receiver)
        
        # Check if they have mutual like
        mutual_like = Like.objects.filter(
            liker=self.sender,
            liked=self.receiver,
            is_mutual=True
        ).exists()
        
        if not are_friends and not mutual_like:
            raise forms.ValidationError("You can only message friends or mutual matches.")
        
        return cleaned_data

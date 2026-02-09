from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, PasswordChangeForm, AuthenticationForm
from .models import UserProfile

class LandingPageForm(forms.Form):
    """Form for landing page preferences"""
    LOOKING_FOR_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('B', 'Both'),
        ('A', 'Anyone'),
    ]
    
    MARITAL_STATUS_CHOICES = [
        ('S', 'Single'),
        ('D', 'Divorced'),
        ('W', 'Widowed'),
        ('N', 'Never Married'),
        ('SEP', 'Separated'),
    ]
    
    AGE_CHOICES = [(i, str(i)) for i in range(18, 121)]
    RELIGIOUS_COMMITMENT_CHOICES = [
        ('V', 'Very Religious'),
        ('M', 'Moderately Religious'),
        ('S', 'Somewhat Religious'),
        ('N', 'Not Religious'),
    ]
    
    # Basic information
    age = forms.ChoiceField(
        choices=AGE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg bg-dark text-white border-dark',
            'style': 'background-color: rgba(0,0,0,0.5); backdrop-filter: blur(10px);'
        })
    )
    
    gender = forms.ChoiceField(
        choices=[('', 'Select Gender'), ('M', 'Male'), ('F', 'Female')],
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg bg-dark text-white border-dark',
            'style': 'background-color: rgba(0,0,0,0.5); backdrop-filter: blur(10px);'
        })
    )
    
    looking_for = forms.ChoiceField(
        choices=[('', 'Looking for...'), ('M', 'Male'), ('F', 'Female'), ('B', 'Both')],
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg bg-dark text-white border-dark',
            'style': 'background-color: rgba(0,0,0,0.5); backdrop-filter: blur(10px);'
        })
    )
    
    marital_status = forms.ChoiceField(
        choices=MARITAL_STATUS_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg bg-dark text-white border-dark',
            'style': 'background-color: rgba(0,0,0,0.5); backdrop-filter: blur(10px);'
        })
    )
    
    # Location
    country = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg bg-dark text-white border-dark',
            'placeholder': 'Country',
            'style': 'background-color: rgba(0,0,0,0.5); backdrop-filter: blur(10px);'
        })
    )
    
    city = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg bg-dark text-white border-dark',
            'placeholder': 'City',
            'style': 'background-color: rgba(0,0,0,0.5); backdrop-filter: blur(10px);'
        })
    )
    
    # Religious information
    sect = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg bg-dark text-white border-dark',
            'placeholder': 'Religious Sect (Optional)',
            'style': 'background-color: rgba(0,0,0,0.5); backdrop-filter: blur(10px);'
        })
    )
    
    religious_commitment = forms.ChoiceField(
        choices=RELIGIOUS_COMMITMENT_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg bg-dark text-white border-dark',
            'style': 'background-color: rgba(0,0,0,0.5); backdrop-filter: blur(10px);'
        })
    )
    
    # Agreement
    terms_agreed = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'style': 'width: 20px; height: 20px;'
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        gender = cleaned_data.get('gender')
        looking_for = cleaned_data.get('looking_for')
        
        # Validate gender and looking_for combination
        if gender and looking_for:
            if gender == looking_for and looking_for in ['M', 'F']:
                raise forms.ValidationError(
                    "If you're looking for someone of the same gender, please select 'Both' in 'Looking for' field."
                )
        
        return cleaned_data



class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter your email'
    }))
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Choose a username'
    }))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Create a password'
    }))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Confirm password'
    }))
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered. Please use a different email or try logging in.")
        return email
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Username or Email'
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Password'
    }))
    
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            'age', 'gender', 'bio', 'profile_pic', 'city', 
            'country', 'sect', 'education', 'practice_level',
            'preferences', 'is_visible', 'show_age', 'show_location',
            'show_sect'
        ]
        widgets = {
            'bio': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Tell us about yourself...'
            }),
            'age': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 18,
                'max': 120
            }),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your city'
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your country'
            }),
            'sect': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your religious/philosophical sect'
            }),
            'education': forms.Select(attrs={'class': 'form-control'}),
            'practice_level': forms.Select(attrs={'class': 'form-control'}),
            'preferences': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter preferences as JSON or key-value pairs'
            }),
            'is_visible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_age': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_location': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_sect': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class UserUpdateForm(UserChangeForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={
        'class': 'form-control'
    }))
    first_name = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control'
    }))
    last_name = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control'
    }))
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('password', None)  # Remove password field


class CustomPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Current password'
        })
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'New password'
        })
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password'
        })
    )


class EmailUpdateForm(forms.Form):
    new_email = forms.EmailField(
        label="New Email Address",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new email address'
        })
    )
    confirm_email = forms.EmailField(
        label="Confirm Email Address",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new email address'
        })
    )
    current_password = forms.CharField(
        label="Current Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your current password'
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        new_email = cleaned_data.get('new_email')
        confirm_email = cleaned_data.get('confirm_email')
        
        if new_email and confirm_email and new_email != confirm_email:
            raise forms.ValidationError("Email addresses don't match.")
        
        return cleaned_data


class AccountDeleteForm(forms.Form):
    password = forms.CharField(
        label="Enter your password to confirm",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Current password'
        })
    )
    confirm_text = forms.CharField(
        label=f"Type 'DELETE MY ACCOUNT' to confirm",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': "Type 'DELETE MY ACCOUNT'"
        })
    )
    
    def clean_confirm_text(self):
        confirm_text = self.cleaned_data.get('confirm_text')
        if confirm_text != 'DELETE MY ACCOUNT':
            raise forms.ValidationError("You must type 'DELETE MY ACCOUNT' exactly to confirm.")
        return confirm_text


class FilterForm(forms.Form):
    """Form for filtering profiles in discover"""
    GENDER_CHOICES = [
        ('', 'Any Gender'),
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    ]
    
    age_min = forms.IntegerField(
        required=False,
        min_value=18,
        max_value=120,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Min Age'
        })
    )
    age_max = forms.IntegerField(
        required=False,
        min_value=18,
        max_value=120,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Max Age'
        })
    )
    city = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'City'
        })
    )
    sect = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Sect'
        })
    )
    education = forms.ChoiceField(
        required=False,
        choices=[('', 'Any Education')] + UserProfile.EDUCATION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    practice_level = forms.ChoiceField(
        required=False,
        choices=[('', 'Any Practice Level')] + UserProfile.PRACTICE_LEVEL_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
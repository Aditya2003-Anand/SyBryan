from django.db import models
from django.contrib.auth.models import User
import uuid



class OAuthToken(models.Model):
    """Stores access tokens for social media integrations"""
    PROVIDER_CHOICES = (
        ("meta", "Meta"),   # Instagram / Facebook
        ("buffer", "Buffer"),
        ("google", "Google"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User,on_delete=models.CASCADE)
    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES)
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, null=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"{self.user.username} - {self.provider}"


class MetaPageDB(models.Model):
    """
    Stores information about Facebook Pages (and linked Instagram accounts)
    a user manages through their Meta connection.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    oauth_token = models.ForeignKey(OAuthToken, on_delete=models.CASCADE, related_name="pages")

    page_id = models.CharField(max_length=255)
    page_name = models.CharField(max_length=255)
    page_access_token = models.TextField()

    instagram_business_id = models.CharField(max_length=255, blank=True, null=True)
    instagram_username = models.CharField(max_length=255, blank=True, null=True)

    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'page_id')

    def __str__(self):
        return f"{self.page_name} ({self.user.username})"


## 13 October


class ContentDB(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    prompt_text = models.TextField()
    caption_text = models.TextField(null=True, blank=True)
    uploaded_image = models.URLField(blank=True,null=True)
    
    generated_image = models.URLField(blank=True, null=True)
    generated_video = models.URLField(blank=True, null=True)

    fb_post_id = models.CharField(max_length=255, blank=True, null=True)
    ig_post_id = models.CharField(max_length=255, blank=True, null=True)

    posted_to_fb = models.BooleanField(default=False)
    posted_to_ig = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Post by {self.user.username} | Prompt: {self.prompt_text[:30]}..."

class WeeklySelection(models.Model):
    content = models.ForeignKey(ContentDB, on_delete=models.CASCADE)
    week_start = models.DateField()  # Monday of the week
    media_type = models.CharField(max_length=10)  # 'VIDEO' or 'PHOTO'
    posted_fb = models.BooleanField(default=False)
    posted_ig = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.media_type} for {self.week_start}: {self.content.id}"


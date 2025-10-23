

#### 14 october


import os
import django
import sys

# Add the project root to sys.path so Django can find the settings
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Django setup ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_video_feed_project.settings")
django.setup()

import random
import time
import schedule
from datetime import datetime, timedelta
from ai_video_feed_app.views import post_instagram, post_facebook,generate_signed_url
from ai_video_feed_app.models import ContentDB, WeeklySelection, MetaPageDB
from django.contrib.auth.models import User

# --- 1. Weekly content selection ---
def select_weekly_content():
    ## Monday 
    today = datetime.now()
    week_start = today.date() - timedelta(days=today.weekday())

    if WeeklySelection.objects.filter(week_start=week_start).exists():
        print(f"[{today}] Weekly selection already exists.")
        return

    # Videos: unposted and has video
    pending_videos = list(ContentDB.objects.filter(posted_to_fb=False, generated_video__isnull=False))
     # Photos: unposted and has image
    pending_photos = list(ContentDB.objects.filter(posted_to_fb=False, generated_video__isnull=True, generated_image__isnull=False))

    if not pending_videos and not pending_photos:
        print(f"[{today}] All content has already been posted. No new content to select for this week.")
        return
  
    selected_videos = random.sample(pending_videos, min(3, len(pending_videos))) if pending_videos else []
    selected_photos = random.sample(pending_photos, min(2, len(pending_photos))) if pending_photos else []

    for item in selected_videos + selected_photos:
        media_type = "Reel" if item.generated_video else "Post"
        WeeklySelection.objects.create(
            content=item,
            week_start=week_start,
            media_type=media_type
        )

    print(f"[{today}] Selected {len(selected_videos)} videos + {len(selected_photos)} photos for the week.")

# --- 2. Daily posting ---
def post_daily_from_weekly_selection():
    today = datetime.now()
    week_start = today.date() - timedelta(days=today.weekday())

    next_item = WeeklySelection.objects.filter(
        week_start=week_start
    ).exclude(posted_fb=True, posted_ig=True).order_by('?').first()

    if not next_item:
        print(f"[{today}] No content left to post today.")
        return

    content = next_item.content
    caption = content.caption_text or ""

    page = MetaPageDB.objects.filter(user__username='user1111').order_by('id').first()
    if not page:
        print("No connected page for user user1111")
        return

    user_for_posting = page.user  # use this exact user object
    print(user_for_posting,"----user")
    page_id = page.page_id
    print(page_id,"----page_id")

    # Generate signed media URL
    original_media_path = content.generated_video if next_item.media_type == "Reel" else content.generated_image

    if original_media_path.startswith("gs://"):
        try:
            signed_media_url = generate_signed_url(original_media_path)
        except Exception as e:
            print(f"❌ Failed to generate signed URL for content id={content.id}: {e}")
            return
    elif original_media_path.startswith(("http://", "https://")):
        signed_media_url = original_media_path
    else:
        print(f"❌ Unsupported media path for content id={content.id}: {original_media_path}")
        return

    # Helper to safely post
    def safe_post(platform, func, **kwargs):
        try:
            post_id = func(**kwargs)
            print(f"✅ {platform} post success: {post_id}")
            return post_id
        except Exception as e:
            print(f"❌ {platform} post failed for content id={content.id}: {e}")
            return None

    # --- Facebook Posting ---
    if not next_item.posted_fb:
        fb_id = safe_post(
            "Facebook",
            post_facebook,
            user=user_for_posting,
            page_id=page_id,
            media_type=next_item.media_type,  
            media_url=signed_media_url,
            caption=caption
        )
        if fb_id:
            next_item.posted_fb = True
            content.posted_to_fb = True
            content.fb_post_id = fb_id

    # --- Instagram Posting ---
    if not next_item.posted_ig:
        ig_media_type = next_item.media_type  # 'Post' or 'Reel'
        ig_id = safe_post(
            "Instagram",
            post_instagram,
            user=user_for_posting,
            page_id=page_id,
            media_url=signed_media_url,
            caption=caption,
            media_type=ig_media_type
        )
        if ig_id:
            next_item.posted_ig = True
            content.posted_to_ig = True
            content.ig_post_id = ig_id

    # Save updates
    next_item.save()
    content.save()
    print(f"[{today}] Completed daily post for content id={content.id}")

# --- 3. Scheduler ---
def run_scheduler():
    # Weekly selection on Monday
    schedule.every().tuesday.at("13:48").do(select_weekly_content)
    # Daily posting every day
    schedule.every().day.at("13:02").do(post_daily_from_weekly_selection)  # few minutes apart

    print("🚀 Scheduler started... Press Ctrl+C to stop.")
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"⚠️ Scheduler error: {e}")
        time.sleep(10)

# --- 4. Main execution ---
if __name__ == "__main__":
    # select_weekly_content()
    # post_daily_from_weekly_selection()
    print(f"[{datetime.now()}] Running scheduler...")
    run_scheduler()

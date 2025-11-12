# your_app/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from django.utils import timezone
from datetime import datetime
from .models import ScheduleContentDB, MetaPageDB
from .views import post_facebook, post_instagram, generate_signed_url

def publish_due_posts():
    """
    Check for scheduled posts due for publishing and post them automatically.
    """
    now = timezone.localtime(timezone.now())
    print("🕒 Checking for due posts...",now)
    current_date = now.date()
    current_time = now.time()
    print("Looking for posts with:")
    print("  date <=", current_date)
    print("  time <=", current_time)

    due_posts = ScheduleContentDB.objects.filter(
        status="scheduled",
        date__lte=current_date,
        time__lte=current_time
    )
    print("Found:", due_posts.count(), "due posts")

    for post in due_posts:
        try:
            print(f"🚀 Publishing scheduled post ID {post.id} for {post.platform}")

            # ✅ Fetch user's connected page for the platform
            try:
                page = MetaPageDB.objects.filter(user=post.user).first()
                if not page:
                    raise Exception("No connected Meta page found for this user.")
            except MetaPageDB.DoesNotExist:
                raise Exception("Meta page not found for user.")

            # ✅ Get media file URL (signed GCS link)
            file_url = generate_signed_url(post.file)

            # ✅ Post to correct platform
            if post.platform.lower() == "facebook":
                post_id = post_facebook(
                    user=post.user,
                    page_id=page.page_id,
                    media_type=post.content_type,
                    media_url=file_url,
                    caption=post.caption
                )

            elif post.platform.lower() == "instagram":
                if not page.instagram_business_id:
                    raise Exception("This page has no linked Instagram business account.")
                post_id = post_instagram(
                    user=post.user,
                    page_id=page.page_id,
                    media_url=file_url,
                    caption=post.caption,
                    media_type=post.content_type
                )

            else:
                raise Exception(f"Unknown platform: {post.platform}")

            # ✅ Mark as published
            post.status = "published"
            post.published_at = timezone.now()
            post.save()

            print(f"✅ Post {post.id} published successfully to {post.platform} ({post_id})")

        except Exception as e:
            print(f"❌ Failed to publish post ID {post.id}: {e}")
            post.status = "failed"
            post.error_message = str(e)
            post.save()

import os
scheduler = None  # Global flag

def start_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        print("⚠️ Scheduler already running, skipping start.")
        return

    if os.environ.get("RUN_MAIN") == "true":
        scheduler = BackgroundScheduler(timezone=timezone.get_current_timezone())
        scheduler.add_job(publish_due_posts, "interval", minutes=1, id="publish_due_posts", replace_existing=True)
        scheduler.start()
        print("🔁 APScheduler started (once): Checking for scheduled posts every 1 minute.")

from django.apps import AppConfig


class AiVideoFeedAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_video_feed_app'

# class AiVideoFeedAppConfig(AppConfig):
#     default_auto_field = "django.db.models.BigAutoField"
#     name = 'ai_video_feed_app'
#
#     def ready(self):
#         from .scheduler import start_scheduler
#         try:
#             start_scheduler()
#         except Exception as e:
#             print(f"⚠️ Scheduler failed to start: {e}")

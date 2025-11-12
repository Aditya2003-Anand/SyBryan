from django.urls import path
from . import views

urlpatterns = [
    path('registration_api', views.RegisterAPI.as_view(), name="register"),  # RegistrationsAPi

    path('signin_api', views.LoginAPI.as_view(), name="signin_api"),  # SigninAPI

    path('signout_api', views.LogoutAPI.as_view(), name="logout"),  ##Signout_api

    path('content_history_api', views.ContentHistoryAPI.as_view(), name="all_content_history"),  ##all_content_history

    path('user_history_api', views.UserHistoryAPI.as_view(), name="user_history_api"),  ##user_history_api

    path('editcontent/<int:pk>/', views.ContentEditAPIView.as_view(), name='editcontent'),

    path('delete_content/<int:pk>/', views.DeleteContentAPIView.as_view(), name='delete_content'),

    path('fetchcontent/<int:pk>/', views.FetchContentAPIView.as_view(), name='FetchContent'),  ##fetchcontentby user

    path('imagecaptiongeneration_api', views.ImageGenEditAPI.as_view(), name="imageGenerationAPI"), ##caption07

    path('videogencaption_api', views.VideoGenerationAPI.as_view(), name="videogencaption_api"), # video + caption8secVeo

    path('textoverimage_api', views.TextImageOverlayingAPI.as_view(), name="textoverimage_api"),  # text image overlay

    path('cm_auto_gen_video_api',views.CMGenerateTemplateVideoAPIView.as_view(),name="cm_auto_gen_video_api"), ##cretomate automationreel05

    path('metalogin_api', views.MetaLoginAPIView.as_view(), name="metalogin_api"),  ##metalogin_api

    path('auth/meta/callback/', views.MetaCallbackAPIView.as_view(), name="MetaCallbackAPIView"),  ##metacallbackapi

    path("meta_conn_status_api", views.MetaConnectionStatusAPIView.as_view(), name="meta-status"),

    path('fb_content_analytics_api', views.FacebookAnalyticsView.as_view(), name='fb_pub_cont_analytics'),

    path('insta_content_analytics_api', views.InstagramAnalyticsView.as_view(), name='InstagramAnalyticsView'),

    path('schedule_content_api', views.ScheduleContentAPIView.as_view(), name='schedule_content'),

    path('scheduled_queue_api', views.FetchScheduledQueueAPIView.as_view(), name='fetch_scheduled_queue'),

    path('cancel_scheduled_content_api/<int:pk>', views.CancelScheduledContentAPIView.as_view(),
         name='cancel_scheduled_content'),

    path('update_scheduled_content_api/<int:pk>', views.UpdateScheduledContentAPIView.as_view(),
         name='update_scheduled_content'),

    # path('imagecaptiongeneration_api', views.ImageGenerationAPI.as_view(), name="imageGenerationAPI"), # ImageGenEditAPI

    path('imageeditingcaption_api', views.ImageEditingAPI.as_view(), name="imageeditingcaption_api"),#caption +  image editing

    path('videogenlg_api', views.FullVideoGenerationAPI.as_view(), name="videogenlg_api"),  # longvideobyVeo

    path('cusreelgen_api', views.CustomReelGeneratorAPI.as_view(), name="cusreelgen_api"),  ##AIcustomereel by user

    path('new_reelGen_api', views.AIContentGenerationAPI.as_view(), name="new_reelGen_api"),

    path("upload_file_api", views.UploadFileView.as_view(), name="upload_url"),

    path('render_video_api', views.RenderVideoAPIView.as_view(), name="render_video_api"),

    path('fetch_templates', views.TemplateListAPIView.as_view(), name="creatomate_templates"),

    path('fetch_templates/<str:template_id>', views.TemplateDetailAPIView.as_view(), name="fetch_single_template"),

    # 12-11-2025
    # path('password_reset_api',views.PasswordResetRequestAPI.as_view(), name='password_reset'),
    # path('password_reset_confirm_api/<uidb64>/<token>',views.PasswordResetConfirmAPI.as_view(), name='password_reset_confirm'),

]
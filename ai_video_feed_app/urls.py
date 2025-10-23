from django.urls import path
from . import views

urlpatterns = [
    path('registration_api',views.RegisterAPI.as_view(),name="register"), #RegistrationsAPi

    path('signin_api',views.LoginAPI.as_view(),name="signin_api"), #SigninAPI

    path('signout_api',views.LogoutAPI.as_view(),name="logout"), ##Signout_api

    path('content_history_api',views.ContentHistoryAPI.as_view(),name="all_content_history"), ##all_content_history

    path('user_history_api',views.UserHistoryAPI.as_view(),name="user_history_api"), ##user_history_api
    
    path('imagecaptiongeneration_api',views.ImageGenerationAPI.as_view(), name="imageGenerationAPI"),### caption + image generation

    path('imageeditingcaption_api',views.ImageEditingAPI.as_view(), name="imageeditingcaption_api"),## caption +  image editing

    path('videogencaption_api',views.VideoGenerationAPI.as_view(),name="videogencaption_api"), ### video + caption8secVeo

    path('videogenlg_api',views.FullVideoGenerationAPI.as_view(),name="videogenlg_api"), # longvideobyVeo
   
    path('metalogin_api',views.MetaLoginAPIView.as_view(),name="metalogin_api"), ##metalogin_api
   
    path('auth/meta/callback/',views.MetaCallbackAPIView.as_view(),name="MetaCallbackAPIView"), ##metacallbackapi
  
    path('facebook_page_feed/', views.FacebookFeedFetchView.as_view(), name='FacebookPageFeed'), #facebook_page_feed
   
    path('textoverimage_api',views.TextImageOverlayingAPI.as_view(),name="textoverimage_api"), #text image overlay
    
    path('editcontent/<int:pk>/', views.ContentEditAPIView.as_view(), name='editcontent'), ##editcontentby_userand thenresend 

    path('delete_content/<int:pk>/', views.DeleteContentAPIView.as_view(), name='delete_content'), ##delete_contentby_user
   
    path('fetchcontent/<int:pk>/', views.FetchContentAPIView.as_view(), name='FetchContent'), ##fetchcontentby user

    path('cusreelgen_api',views.CustomReelGeneratorAPI.as_view(),name="cusreelgen_api"), ##AIcustomereel by user

    # path('facebook-share', views.FacebookShareURLView.as_view(), name='facebook-share'),

    path('facebookpost_api', views.FacebookPostAPIView.as_view(), name='facebookpost_api'), ##facebookpost_api
  
    path('instagrampost_api', views.InstagramPostAPIView.as_view(), name='instagrampost_api'), ##instagrampost_api
    
    path('weeklysellist_api', views.WeeklySelectionListAPI.as_view(), name='weeklysellist_api'), ##weeklysellist_api

    

]

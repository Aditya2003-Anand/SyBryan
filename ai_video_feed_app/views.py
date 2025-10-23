from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth.models import User
from django.db.models import Q
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate, login,logout
from rest_framework.permissions import IsAuthenticated
from .serializers import ContentSerializer
from .models import ContentDB,MetaPageDB
from google import genai
import os
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from google.genai import types
from urllib.parse import urlparse
from PIL import Image 
from io import BytesIO
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from google.cloud import storage
from datetime import timedelta
from moviepy.editor import VideoFileClip, concatenate_videoclips
from moviepy.audio.fx.all import audio_normalize
from PIL import Image, UnidentifiedImageError
import os
from io import BytesIO
import uuid
import base64
import requests
import re
import time
import tempfile
import os
import tempfile
import shutil
from pathlib import Path
import subprocess
import librosa
import math
from django.conf import settings
import json
from datetime import timedelta
from django.utils import timezone
from .models import OAuthToken
from django.core.signing import Signer
from django.shortcuts import get_object_or_404

from datetime import timedelta
from django.utils import timezone
from .models import OAuthToken
 
from rest_framework import generics
from .models import WeeklySelection
from .serializers import WeeklySelectionSerializer


load_dotenv()

GOOGLE_APPLICATION_CREDENTIALS=os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
api_key = os.getenv('GEMINI_API_KEY')
bucket_name=os.getenv('bucket_name')
PROJECT_ID = os.getenv('project_id')
PROJECT_ID = os.getenv('project_id')
LOCATION = os.getenv('region')

client=genai.Client()
video_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
storage_client = storage.Client(project=PROJECT_ID)
output_prefix = f"gs://{bucket_name}/generated_videos/{int(time.time())}"

## meta api 
META_APP_ID = os.getenv('META_APP_ID')
META_APP_SECRET =os.getenv('META_APP_SECRET')
BASE_URL = os.getenv('BASE_URL')


####### Register 
class RegisterAPI(APIView):
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        first_name = request.data.get("first_name")
        last_name = request.data.get("last_name")
        email = request.data.get("email")

        if not username or not password or not first_name or not last_name or not email:
            return Response(
                {"success": False, "message": "All fields are required","error": True},
                status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=username).exists():
            return Response(
                {"success": False, "message": "Username already exists","error": True },
                status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email=email).exists():
            return Response(
                {"success": False, "message": "Email already exists","error": True,},
                status=status.HTTP_400_BAD_REQUEST )
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password,
            )
            if user:
                token, _ = Token.objects.get_or_create(user=user)
                
                user_dict = {
                    "id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "token_key": token.key,
                }
                return Response(
                    {"success": True,"message": "User successfully registered", "data": user_dict,"error": False},
                    status=status.HTTP_201_CREATED,
                )
        except Exception as e:
            return Response(
                {
                    "success": False,"message": "Unable to register user", "details": str(e),"error": True},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR )

######Login API

## function to login through username or email 
def get_user(username):
    try:
        user = User.objects.filter(
            Q(email__iexact=username) | Q(username__iexact=username)
        ).first()
        return user
    except Exception as e:
        # print("Error in get_user:", e)
        return None

class LoginAPI(APIView):
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        if not username or not password:
            return Response(
                {
                    "success": False,
                    "message": "Both username and password fields are required",
                    "error": True,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = get_user(username)
        if not user:
            return Response(
                {"success": False, "message": "Invalid Credentials","error": True},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user_data = authenticate(username=user.username, password=password)

        if not user_data:
            return Response(
                {"success": False, "message": "Invalid Credentials","error": True,},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token, _ = Token.objects.get_or_create(user=user_data)
        login(request, user)
        return Response(
            {
                "success": True,
                "message": "User Logged In Successfully",
                "data": {
                    "id": user_data.id,
                    "username": user_data.username,
                    "email": user_data.email,
                    "token_key": token.key,
                },
                "error": False
            },
            status=status.HTTP_200_OK
        )

## Logout 
class LogoutAPI(APIView) :
    permission_classes=[IsAuthenticated]
    def post(self,request) :
        logout(request)
        return Response({"success":True,"message":"User Logged out successfully","error":False})
    
# Fetch content history for a specific user by email
class UserHistoryAPI(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        email = request.query_params.get("email")
        if not email:
            return Response({
                "success": False,
                "message": "Email query parameter is required",
                "data": [],
                "error": True
            }, status=400)

        try:
            user = User.objects.get(email__iexact=email)
            if user != request.user:
                return Response(
                    {"error": "You do not have permission to access this content."},
                    status=status.HTTP_403_FORBIDDEN
                )
        except User.DoesNotExist:
            return Response({
                "success": False,
                "message": f"No user found with email {email}",
                "data": [],
                "error": True
            }, status=404)

        # Fetch all content for this user, newest first
        contents = ContentDB.objects.filter(user=user).order_by('-created_at')
        serializer = ContentSerializer(contents, many=True)
        return Response({
            "success": True,
            "message": f"Content history for {user.username} fetched",
            "data": serializer.data,
            "error": False
        }, status=200)


# Fetch all contents on the db newest first
class ContentHistoryAPI(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        query_data = ContentDB.objects.all().order_by('-created_at')
        serializer = ContentSerializer(query_data, many=True)
        return Response({
            "success": True,
            "message": "All Content History Fetched Successfully",
            "data": serializer.data,
            "error": False
        }, status=200)

class FetchContentAPIView(APIView) :
    permission_classes=[IsAuthenticated]
    def get(self,request,pk) :
        content=get_object_or_404(ContentDB,pk=pk)
        if content.user != request.user:
            return Response(
                {"error": "You do not have permission to delete this content."},
                status=status.HTTP_403_FORBIDDEN
            )        
        data = {
            "id": content.id,
            "user": content.user.username,
            "prompt_text": content.prompt_text,
            "caption_text": content.caption_text,
            "uploaded_image": content.uploaded_image,
            "generated_image": content.generated_image,
            "generated_video": content.generated_video,
            "fb_post_id": content.fb_post_id,
            "ig_post_id": content.ig_post_id,
            "posted_to_fb": content.posted_to_fb,
            "posted_to_ig": content.posted_to_ig,
            "created_at": content.created_at,
            "updated_at": content.updated_at,
        }
        return Response({"success":True ,"message":f"Content with ID {pk} fetched successfully." ,"data":data,"error":False}, status=status.HTTP_200_OK)
  
class ContentEditAPIView(APIView):
    """
    API to edit ContentDB items (caption, generated_image, generated_video).
    If the content has already been published in WeeklySelection and now changes have been made , reset posted flags
    so it can be republished.
    """
    permission_classes=[IsAuthenticated]
    def put(self, request, pk, format=None):
        content = get_object_or_404(ContentDB,pk=pk)
        if content.user != request.user:
            return Response(
                {"error": "You do not have permission to edit this content."},
                status=status.HTTP_403_FORBIDDEN
            )
        
         # --- Track original values ---
        original_values = {
            "caption_text": content.caption_text,
            "generated_image": content.generated_image,
            "generated_video": content.generated_video,
        }

        # --- Extract fields from request (partial update) ---
        caption_text = request.data.get("caption_text", content.caption_text)
        generated_image = request.data.get("generated_image", content.generated_image)
        generated_video = request.data.get("generated_video", content.generated_video)

        # --- Update Fields ---
        content.caption_text = caption_text
        content.generated_image = generated_image
        content.generated_video = generated_video
        content.save()

        # --- Detect actual changes ---
        changed = any(
            original_values[field] != getattr(content, field)
            for field in original_values
        )

            # Republishing logic: mark WeeklySelection as unposted if already posted and changes made
        if changed :
            weekly_items = WeeklySelection.objects.filter(content=content)
            for item in weekly_items:
                if item.posted_fb or item.posted_ig:
                    item.posted_fb = False
                    item.posted_ig = False
                    item.save()

                # Reset ContentDB posted flags as well
            if content.posted_to_fb or content.posted_to_ig:
                content.posted_to_fb = False
                content.posted_to_ig = False
                content.save()
            
            message = f"Content with ID {pk} updated successfully (changes detected)"
        else:
            message = f"Content with ID {pk} updated successfully (no changes detected)."       
        # --- Success Response ---
        data = {
            "id": content.id,
            "caption_text": content.caption_text,
            "generated_image": content.generated_image,
            "generated_video": content.generated_video,
            "posted_to_fb": content.posted_to_fb,
            "posted_to_ig": content.posted_to_ig,
            "updated_at": content.updated_at,
        }
        return Response({
                "success": True,
                "message": message,
                "data": data,
                "error": False,
            },status=status.HTTP_200_OK)

class DeleteContentAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            content = get_object_or_404(ContentDB, pk=pk)

            if content.user != request.user:
                return Response({
                    "success": False,
                    "message": "You do not have permission to delete this content.",
                    "data": None,
                    "error": True
                }, status=status.HTTP_403_FORBIDDEN)

            caption_text = content.caption_text
            content.delete()

            return Response({
                "success": True,
                "message": f"Content with ID {pk} deleted successfully.",
                "data": {"caption_text": caption_text},
                "error": False
            }, status=status.HTTP_200_OK)

        except ContentDB.DoesNotExist:
            return Response({
                "success": False,
                "message": f"Content with ID {pk} not found.",
                "data": None,
                "error": True
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({
                "success": False,
                "message": "Content already deleted.",
                "data": None ,
                "error": True
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

######################## uploading to GCS 

def upload_file_to_gcs(bucket_name, file_bytes, file_type):
    bucket = storage_client.bucket(bucket_name)
    # Determine content type and extension
    if file_type == "image":
        content_type = "image/png"
        folder = "images"
        extension = "png"
    elif file_type == "video":
        content_type = "video/mp4"
        folder = "videos"
        extension = "mp4"
    else:
        raise ValueError("file_type must be 'image' or 'video'")
    # Generate unique filename
    unique_id = uuid.uuid4().hex[:8]
    destination_blob_name = f"{folder}/generated_{file_type}_{unique_id}.{extension}"
    # Upload bytes to GCP
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_file(BytesIO(file_bytes), content_type=content_type)
    gcs_path = f"gs://{bucket_name}/{destination_blob_name}"
    # print(gcs_path,"------- gcs path of uploaded file")
    return gcs_path

def parse_gcs_uri(uri):
    parsed = urlparse(uri)
    if parsed.scheme != "gs":
        raise ValueError(f"Invalid GCS URI: {uri}")
    return parsed.netloc, parsed.path.lstrip('/')

def generate_signed_url(gcs_path, expiration_days=7):
    bucket_name, object_name = parse_gcs_uri(gcs_path)
    blob = storage_client.bucket(bucket_name).blob(object_name)

   # Retry until blob exists or timeout
    retries = 10
    for _ in range(retries):
        if blob.exists():
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(days=expiration_days)
            )
            expiration_td = timedelta(days=expiration_days)
            # print(f"\n\n DEBUG: Expiration timedelta set to: {expiration_td}\n\n")

            # print(signed_url, "-> Signed URL of uploaded file")
            return signed_url
        time.sleep(2)

    raise RuntimeError("Blob does not exist in GCS after waiting.")


def process_and_upload_image(image_file):
    """
    Converts an uploaded image to bytes, uploads it to GCS,
    and returns image bytes, GCS path, and signed URL.
    Args:
        image_file: File-like object (from request.FILES or similar)
    Returns:
        tuple: (image_bytes, user_image_gcs_path, user_image_signed_url)
    """
    # Open image
    try:
        image = Image.open(image_file)
    except UnidentifiedImageError:
        raise ValueError("Uploaded file is not a valid image.")
    # Convert to bytes
    image_buffer = BytesIO()
    image.save(image_buffer, format=image.format)
    image_bytes = image_buffer.getvalue()
    # Use Pillow's format as mime_type
    mime_type = image.format
    # print(len(image_bytes), "-----image converted")
    # print("MIME type:", mime_type)
    # Upload to GCS
    user_image_gcs_path = upload_file_to_gcs(bucket_name, image_bytes, file_type="image")
    # print(user_image_gcs_path, "---uploaded image saved to GCS")
    # Generate signed URL
    user_image_signed_url = generate_signed_url(user_image_gcs_path, expiration_days=7)
    return image_bytes, mime_type, user_image_gcs_path, user_image_signed_url

################ Content Generation 
#gemini-2.5-flash
def generate_text(prompt):
        # final_prompt = prompt
        final_prompt = f"User query is: {prompt}. Respond to the user's query in a brief, concise, and meaningful way while ensuring clarity. Use complete sentences."
        # print(final_prompt,"---final prompt for casual texting or caption")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=final_prompt
        )
        return response.text.strip()

def clean_gemini_text(text: str, escape_ffmpeg: bool = False) -> str:
    """
    Cleans and formats text generated by Gemini.
    Args:
        text (str): Input text.
        escape_ffmpeg (bool): If True, escape special characters for FFmpeg drawtext.

    Returns:
        str: Cleaned text.
    """
    if not text:
        return ""

    # 1. Remove markdown/code artifacts
    text = re.sub(r'```[\w]*\n', '', text)  # opening code block
    text = re.sub(r'\n```', '', text)       # closing code block

    # 2. Remove excessive newlines
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)

    # 3. Strip leading/trailing whitespace
    text = text.strip()

    # 4. Optionally escape FFmpeg drawtext special characters
    if escape_ffmpeg:
        text = text.replace("'", r"'\''")  # single quote
        text = text.replace("\\", r"\\")   # backslash
        text = text.replace(":", r"\:")    # colon
        text = text.replace(",", r"\,")    # comma

    # 5. Normalize whitespace (spaces & newlines)
    text = re.sub(r'\s+', ' ', text)
    return text

def generate_caption(file_bytes,file_type) :
    if file_type == "video":
        mime_type = "video/mp4"
        prompt = """
Your task is to analyze the given video.
And generate an attractive caption about the given video for a social-media platform.
And Caption should be Uniques and more Engaging .
The caption should be a complete sentence with appropriate hashtags. 
Important Note: Do not give descriptions out of context and do not use emojis.
"""
    elif file_type == "image":
        # You can adjust if your images are PNG/JPEG
        mime_type = "image/png"
    else:
        raise ValueError("file_type must be 'video' or 'image'")

    # Send request to Gemini
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=types.Content(
            parts=[
                types.Part(
                    inline_data=types.Blob(data=file_bytes, mime_type=mime_type)
                ),
                types.Part(text=prompt),
            ]
        ),
    )
    # Extract text response
    caption_text = response.text if hasattr(response, "text") else str(response)
    # print("Generated caption :",caption_text)
    return caption_text

def generate_image_text(prompt, image=None):
    contents = [prompt]
    if image is not None:
        contents.append({
            "inline_data": {
                "mime_type": "image/png",
                "data": image
            }
        })
    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=contents,
    )
    generated_text, generated_image = None, None
    if response.candidates:
        # print(response.candidates[0].content.parts,"--------")
        for part in response.candidates[0].content.parts:
            if part.text:
                generated_text = part.text
                # print(generated_text, "---caption generated")
            elif part.inline_data:
                generated_image = Image.open(BytesIO(part.inline_data.data))
                # print(generated_image, "----generated_image_object")
    return {"text": generated_text, "image": generated_image}

########video #########
def generate_video(prompt =None,image_bytes=None,mime_type="PNG" ) :
    # print("prompt received ",prompt)
    if not  image_bytes :
        operation = client.models.generate_videos(
    model="veo-3.0-fast-generate-001",
    prompt=prompt)
    else :
        image_input = types.Image(
                image_bytes=image_bytes,
                mime_type=mime_type
            )
        # print("image input received")
        operation = client.models.generate_videos(
                model="veo-3.0-fast-generate-001",
                prompt=prompt,
                image=image_input,
                config=types.GenerateVideosConfig(
                    aspect_ratio="9:16",
                    resolution="720p",
                    number_of_videos=1,
                    negative_prompt="ugly, low quality"
                )
            )  
        
    # Poll for completion
    timeout = 900
    poll_interval = 21
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise TimeoutError("Video generation timed out.")
        operation = client.operations.get(operation)
        if operation.done:
            break
        time.sleep(poll_interval)

    if operation.error:
        raise RuntimeError(f"Generation failed: {operation.error}")

    videos = operation.result.generated_videos
    if not videos:
        raise RuntimeError("No videos returned in the result.")

   
    video_file = operation.response.generated_videos[0]
    video_bytes = client.files.download(file=video_file.video.uri)
    # print("--------video generated by model ! ")
    return video_bytes

######################## APIS
# 1. VideoGeneration + caption/hastag -- veo + flash
class VideoGenerationAPI(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,request):
        user=request.user
        prompt=request.data.get("prompt","")
        # print(prompt,"--prompt")
        image=request.FILES.get("image",None)

        ## upload the user image in google storage
        user_image_gcs_url = user_image_signed_url = None
        if image:
                image_bytes,mime_type,user_image_gcs_url,user_image_signed_url = process_and_upload_image(image)
       
        if prompt and not image :
            generated_video_bytes = generate_video(prompt)
        else :
            generated_video_bytes = generate_video(prompt, image_bytes if image else None,mime_type)

        if generated_video_bytes:
            generated_video_gcs_url = upload_file_to_gcs(bucket_name, generated_video_bytes, file_type="video")
            generated_video_signed_url = generate_signed_url(generated_video_gcs_url)
        else:
            generated_video_gcs_url = generated_video_signed_url = None

        caption_text = generate_caption(generated_video_bytes, file_type="video")
        cleaned_text = clean_gemini_text(caption_text)   
        final_cleaned_data=cleaned_text +" " + "#MilanoCafe" + " "+ "#milanocafe_official"+" "+ "#milanocafe"
        # print(final_cleaned_data,"----------final_caption")
        content =ContentDB.objects.create(
            user=user,
            prompt_text = prompt,
            caption_text = final_cleaned_data if final_cleaned_data else None,
            uploaded_image= user_image_gcs_url  if user_image_gcs_url  else None,
            generated_video=generated_video_gcs_url if generated_video_gcs_url else None
        )
        # print(content,"------content stored")
        final_response ={
            "user" : content.user.username,
            "user_prompt": prompt,
            "generated_caption":final_cleaned_data,
            "uploaded_image" :user_image_signed_url  if user_image_signed_url  else None,
            "generated_video" :generated_video_signed_url if generated_video_signed_url else None
        }
        return Response({"success":True,"message":"Generated Successfully","response":final_response,"error":False},status=status.HTTP_200_OK)


###NewUpdatedAPI22OCT25:   

class ImageEditingAPI(APIView):
    permission_classes = [IsAuthenticated]
 
    def post(self, request):
        user = request.user
        prompt = request.data.get("prompt")
        uploaded_image = request.FILES.get("image")
        image_url = request.data.get("image_url")
 
        if not prompt or (not uploaded_image and not image_url):
            return Response(
                {"success": False, "message": "Prompt and either image file or image URL are required", "error": True},
                status=status.HTTP_400_BAD_REQUEST
            )
 
        if uploaded_image and image_url:
            return Response(
                {"success": False, "message": "Please provide either an image file or an image URL, not both.", "error": True},
                status=status.HTTP_400_BAD_REQUEST
            )
 
        # Handle uploaded image from device
        if uploaded_image:
            # Upload the user image to GCS
            image_bytes, mime_type, user_image_gcs_url, user_image_signed_url = process_and_upload_image(uploaded_image)
        # Handle image URL
        else:
            
            try:
                response = requests.get(image_url)
                response.raise_for_status()
                image_bytes = response.content
                parsed = urlparse(image_url)
                object_path = parsed.path.lstrip('/').replace(f'{bucket_name}/', '', 1)
                user_image_gcs_url = f"gs://{bucket_name}/{object_path}"
 
                user_image_signed_url = image_url  # keep full URL for access
 
            except requests.exceptions.RequestException as e:
                return Response(
                    {"success": False, "message": f"Failed to fetch image from URL: {str(e)}", "error": True},
                    status=status.HTTP_400_BAD_REQUEST
                )
        # Prepare prompt
        final_prompt = f"""{prompt}  
            Edit the provided image based on the instructions.  
            Also, generate a concise social media caption for the edited image following these rules:  
            The caption must:  
            - Be a complete, natural sentence.  
            - Caption should be Uniques and more Engaging .  
            - Include relevant hashtags.  
            - Stay strictly within the context of the given image and prompt.  
            Do not:  
            - Use emojis.  
            - Add phrases like "Here's a caption for social media".  
            - Include unrelated details.  
            """
 
        # Generate edited image and caption
        result = generate_image_text(final_prompt, image_bytes)
        response_text = result.get("text")
        response_image = result.get("image")
        cleaned_text = clean_gemini_text(response_text)
        final_cleaned_data = cleaned_text + " #MilanoCafe #milanocafe_official #milanocafe"
        print(final_cleaned_data, "----------final_caption")
 
        # Upload generated image to GCS
        generated_image_gcs_url = generated_image_signed_url = None
        if response_image:
            img_bytes = BytesIO()
            response_image.save(img_bytes, format="PNG")
            img_bytes = img_bytes.getvalue()
            generated_image_gcs_url = upload_file_to_gcs(bucket_name, img_bytes, file_type="image")
            generated_image_signed_url = generate_signed_url(generated_image_gcs_url)
 
        # Save to DB
        content = ContentDB.objects.create(
            user=user,
            prompt_text=prompt,
            caption_text=final_cleaned_data,
            uploaded_image=user_image_gcs_url,
            generated_image=generated_image_gcs_url if generated_image_gcs_url else None
        )
 
        final_response = {
            "user": content.user.username,
            "generated_caption": final_cleaned_data,
            "uploaded_image": user_image_signed_url,
            "generated_image": generated_image_signed_url if generated_image_signed_url else None
        }
 
        return Response({"success": True, "message": "Generated Successfully", "response": final_response, "error": False},
                        status=status.HTTP_200_OK)


# 2. Image Generation  + caption/hastag    -- flash 
class ImageGenerationAPI(APIView) :
    permission_classes=[IsAuthenticated]
    def post(self,request):
        user=request.user
        prompt=request.data.get("prompt")
        # print(prompt,"--prompt")
        if not prompt :
             return Response({"success":False,"message" :"prompt field is required","error":True},status=status.HTTP_400_BAD_REQUEST)


        final_prompt = f"""
        Generate a high-quality, visually appealing image based on the user's prompt: {prompt}.

        Then, create a concise social media caption for the generated image with these rules:
            - Must be a complete, natural sentence.
            - Unique, engaging, and relevant to the image.
            - Include appropriate hashtags.
            - Stay strictly within the context of the image and prompt.

        Do not:
            - Use emojis.
            - Include phrases like "Here's a caption for social media."
            - Add unrelated details or context.
        """

        result = generate_image_text(final_prompt)
        response_text = result.get("text")
        response_image = result.get("image")
        cleaned_text = clean_gemini_text(response_text) 
        final_cleaned_data=cleaned_text +" " + "#MilanoCafe" + " "+ "#milanocafe_official"+" "+ "#milanocafe"
        # print(final_cleaned_data,"----------final_caption")

        generated_image_gcs_url = generated_image_signed_url = None
        if response_image :
            img_bytes = BytesIO()
            response_image.save(img_bytes, format="PNG")
            img_bytes = img_bytes.getvalue()
            generated_image_gcs_url  = upload_file_to_gcs(bucket_name,img_bytes,file_type="image")      
            generated_image_signed_url  =generate_signed_url(generated_image_gcs_url )  
            content =ContentDB.objects.create(
            user=user,
            prompt_text = prompt,
            caption_text = final_cleaned_data if final_cleaned_data else None,
            
            generated_image= generated_image_gcs_url  if generated_image_gcs_url  else None
        )
        final_response ={
            "user" : content.user.username,
            "generated_caption":final_cleaned_data,
            "generated_image" :generated_image_signed_url  if generated_image_signed_url  else None
        }
        return Response({"success":True,"message":"Generated Successfully","response":final_response,"error":False},status=status.HTTP_200_OK)


#### 14 october --- text over image + caption/hashtag
class TextImageOverlayingAPI(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,request) :
        user=request.user
        prompt=request.data.get("prompt","").strip()
        # print(prompt,"-----prompt")
        image=request.FILES.get("image",None)
        # required field - TextImageOverlayingAPI
        if not image and not prompt :
            return Response({"success":False,"message":"either image or prompt field is required","error":True})
        # print(image,"------image")
        if prompt and image:
            # print("\n-------\n")
            final_prompt = f"""
Use the uploaded image as a base and interpret the following theme: "{prompt}".

Create a new, enhanced version of the image that naturally integrates attention-grabbing text overlay matching the theme.
The model should decide the best font style, size, placement, and color to make the image visually appealing, readable, and aligned with modern social media aesthetics.

Also, generate:
- One short, witty, and engaging caption (max 40 words).
- 4–5 relevant hashtags.

Important:
- Keep everything contextually relevant.
- Do not use emojis.
- Do not use phrases like "Here's a caption for social media."
- Focus on beauty, coherence, and emotional appeal rather than literal interpretation.
"""         
            
            
        elif prompt :
            final_prompt = f"""
    Create an image based on the following description: "{prompt}".
    Overlay  attention-grabbing texts directly on the image.
    Also, generate a short, funny, and engaging caption for social media that is no longer than 40 words.
    Design both the image and the overlayed text to be eye-catching, readable, and aesthetically harmonious.
    Important Note: Do not give descriptions out of context , Do not give emojis And Do Not Use this words 'Here's a caption for social media:'
    """
        elif image :
            final_prompt=f"""Analyze the uploaded image in detail.Based on the image's content, context, and visual style:
1.  **IMAGE EDITING (CRITICAL):** Generate a more enhanced **NEW VERSION** of this image. The new image must have some  attention-grabbing texts overlay placed directly on it. The text should be relevant to the image, visually appealing, easy to read on small screens, and follow modern social media aesthetics.
2.  **TEXT GENERATION:** Generate a short, witty, and engaging social media caption (max 40 words) and 4-5 relevant hashtags.
Important Note: Do not give descriptions out of context , Do not give emojis And Do Not Use this words 'Here's a caption for social media:'
"""   
        user_image_gcs_url =user_image_signed_url = None 
        if image :
            image_bytes,mime_type,user_image_gcs_url,user_image_signed_url = process_and_upload_image(image)
            result = generate_image_text(final_prompt,image_bytes)
        else :
            result = generate_image_text(final_prompt) 
        
        response_text = result.get("text")
        response_image = result.get("image")

        cleaned_text = clean_gemini_text(response_text)
        final_cleaned_data=cleaned_text +" " + "#MilanoCafe" + " "+ "#milanocafe_official"+" "+ "#milanocafe"
        # print(final_cleaned_data,"----------final_caption")

        generated_image_gcs_url =generated_image_signed_url =  None
        if response_image :
            img_bytes = BytesIO()
            response_image.save(img_bytes, format="PNG")
            img_bytes = img_bytes.getvalue()
            generated_image_gcs_url  = upload_file_to_gcs(bucket_name,img_bytes,file_type="image")
            # print(generated_image_gcs_url ,"---db image url")
            generated_image_signed_url  =generate_signed_url(generated_image_gcs_url )
            # print(generated_image_signed_url ,"------image url")

        content =ContentDB.objects.create(
            user=user,
            prompt_text = prompt,
            caption_text = final_cleaned_data if final_cleaned_data else None,
            uploaded_image = user_image_gcs_url if user_image_gcs_url else None,
            generated_image= generated_image_gcs_url  if generated_image_gcs_url  else None
        )
        final_response ={
            "user" : content.user.username,
            "generated_caption":final_cleaned_data,
            "uploaded_image":user_image_signed_url if user_image_signed_url else None,
            "generated_image" :generated_image_signed_url  if generated_image_signed_url  else None
        }

        return Response({"success":True,"message":"Generated Successfully","response":final_response,"error":False},status=status.HTTP_200_OK)




FFMPEG_PATH = r""
FFPROBE_PATH = r""
DEFAULT_MUSIC = os.path.join(settings.BASE_DIR, "")
MAX_IMAGE_DURATION = 3
MIN_IMAGE_DURATION = 2
NORMALIZED_RESOLUTION = "1280:720"
NORMALIZED_FPS = 30
MAX_DURATION = 60
FADE_DURATION = 0.5
TRANSITION_DURATION = 1

def generate_overlay_text_for_video(file_bytes):
    mime_type = "video/mp4"
    prompt = """
You are a social media video editor. Analyze this video and generate a single, concise text suitable for overlay. 
The text should be one line, catchy, and engaging. 
Do NOT use hashtags, emojis, Markdown formatting, or line breaks.

"""

    import time
    start = time.time()


    # Send request to Gemini-Flash
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=types.Content(
            parts=[
                types.Part(
                    inline_data=types.Blob(data=file_bytes, mime_type=mime_type)
                ),
                types.Part(text=prompt)
            ]
        ),
    )
    # print("Generation took:", time.time() - start, "seconds")

    overlay_text = response.text if hasattr(response, "text") else str(response)
    overlay_text = clean_gemini_text(overlay_text, escape_ffmpeg=True)

    # print("Generated overlay text:", overlay_text)
    return overlay_text

# fully working   ( transition + overlaying + scalable )
class CustomReelGeneratorAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):

        # Get uploaded files
        uploaded_files = request.FILES.getlist("files")
        if not uploaded_files:
            return Response({"error": "No files uploaded"}, status=400)
        
        num_uploaded = len(uploaded_files)

        # Limit clips: minimum 2, maximum 5
        if num_uploaded < 2:
            return Response({"error": "At least 2 clips are required"}, status=400)
        if num_uploaded > 5:
            return Response({"error": "A maximum of 5 clips are allowed"}, status=400)

        opts = request.POST.get("transition_options", "{}")
        try:
            opts = json.loads(opts)
        except json.JSONDecodeError:
            opts = {}
        overlay_opts = request.POST.get("overlay_text", "{}")
        try:
            overlay_opts = json.loads(overlay_opts)
        except json.JSONDecodeError:
            overlay_opts = {}
        overlay_enabled = overlay_opts.get("enabled", False)


        temp_dir = tempfile.mkdtemp()

        def get_video_duration(path):
            try:
                result = subprocess.run(
                    [FFPROBE_PATH, "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", path],
                    capture_output=True, text=True, check=True
                )
                return float(result.stdout.strip())
            except:
                return None

        def normalize_and_overlay_clip(input_path, output_path, is_image=False, duration=3,
                                       text=None, fontcolor="white", fontsize=46,
                                       position="center-bottom", animation="static"):
            cmd = [FFMPEG_PATH, "-y"]
            if is_image:
                cmd += ["-loop", "1", "-i", input_path, "-t", str(duration)]
            else:
                cmd += ["-i", input_path]

            filters = [
                "scale=1280:720:force_original_aspect_ratio=decrease",
                "pad=1280:720:(1280-iw)/2:(720-ih)/2:color=black",
                f"fps={NORMALIZED_FPS}"
            ]

            if text:
                text = clean_gemini_text(text,escape_ffmpeg=True)
                positions = {
                    "top-left": "x=50:y=100",
                    "top-right": "x=w-tw-50:y=100",
                    "bottom-left": "x=50:y=h-th-150",
                    "bottom-right": "x=w-tw-50:y=h-th-150",
                    "center": "x=(w-text_w)/2:y=(h-text_h)/2",
                    "top-center": "x=(w-text_w)/2:y=100",
                    "center-bottom": "x=(w-text_w)/2:y=h-th-150"
                }
                pos = positions.get(position, positions["center-bottom"])

                if animation == "fadein":
                    drawtext = f"drawtext=text='{text}':fontcolor={fontcolor}:fontsize={fontsize}:{pos}:alpha='if(lt(t,2), t/2,1)'"
                elif animation == "fadeout":
                    drawtext = f"drawtext=text='{text}':fontcolor={fontcolor}:fontsize={fontsize}:{pos}:alpha='if(gt(t,{duration-2}), ({duration}-t)/2,1)'"
                elif animation == "move":
                    drawtext = f"drawtext=text='{text}':fontcolor={fontcolor}:fontsize={fontsize}:x='100*t':y=(h-text_h)/2"
                elif animation == "combo":
                    drawtext = f"drawtext=text='{text}':fontcolor={fontcolor}:fontsize={fontsize}:x='100*t':y=(h-text_h)/2:alpha='if(lt(t,2), t/2,1)'"
                else:
                    drawtext = f"drawtext=text='{text}':fontcolor={fontcolor}:fontsize={fontsize}:{pos}"

                filters.append(drawtext)

            cmd += ["-vf", ",".join(filters)]
            cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k", "-ac", "2", output_path]

            subprocess.run(cmd, check=True)
            return output_path

        def apply_transitions(clips, output_path, transition_type="fade"):
            if len(clips) == 1 or transition_type.lower() == "none":
                shutil.copy(clips[0], output_path)
                return output_path

            trans_map = {
                "fade": "fade", "fadeblack": "fadeblack", "fadewhite": "fadewhite",
                "slideleft": "slideleft", "slideright": "slideright",
                "slideup": "slideup", "slidedown": "slidedown",
                "wiperight": "wiperight", "wipeleft": "wipeleft",
                "wipeup": "wipeup", "wipedown": "wipedown",
                "circleopen": "circleopen", "circleclose": "circleclose",
                "radial": "radial", "smoothleft": "smoothleft", "smoothright": "smoothright",
                "pixelize": "pixelize", "dissolve": "dissolve"
            }

            trans = trans_map[transition_type.lower()]

            inputs = []
            for clip in clips:
                inputs.extend(["-i", clip])
            inputs.extend(["-i", DEFAULT_MUSIC])
            music_index = len(clips)

            filter_cmds = []
            cumulative_time = 0
            for i in range(1, len(clips)):
                prev_duration = get_video_duration(clips[i-1]) or 2
                offset = cumulative_time + prev_duration - TRANSITION_DURATION
                in1 = "[0:v]" if i == 1 else f"[v{i-1}]"
                in2 = f"[{i}:v]"
                out_label = f"[v{i}]"
                filter_cmds.append(f"{in1}{in2} xfade=transition={trans}:duration={TRANSITION_DURATION}:offset={offset} {out_label}")
                cumulative_time += prev_duration

            filter_complex = ";".join(filter_cmds)
            cmd = [
                FFMPEG_PATH, "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", f"[v{len(clips)-1}]",
                "-map", f"{music_index}:a",
                "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-ac", "2",
                    "-shortest",
                output_path
            ]
            subprocess.run(cmd, check=True)
            return output_path

        try:
            clips = []
            for f in uploaded_files:
                path = os.path.join(temp_dir, f.name)
                with open(path, "wb") as out_file:
                    for chunk in f.chunks():
                        out_file.write(chunk)
                ext = path.lower().split(".")[-1]
                if ext in ["mp4", "mov", "avi", "mkv"]:
                    clips.append({"path": path, "type": "video"})
                elif ext in ["jpg", "jpeg", "png"]:
                    tmp_clip = os.path.join(temp_dir, f"tmp_{f.name}.mp4")
                    clips.append({"path": path, "type": "image", "tmp": tmp_clip})

            # Beat detection (optional, for future sync)
            y, sr = librosa.load(DEFAULT_MUSIC, sr=None)
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)
            beat_times = beat_times[beat_times <= 60]

            normalized_clips = []
            for i, clip in enumerate(clips):
                duration = 3
                if clip["type"] == "video":
                    duration = max(2, min(get_video_duration(clip["path"]) or 3, duration))
                    out_path = os.path.join(temp_dir, f"normalized_{i}.mp4")
                    text = None
                    if overlay_enabled:
                        text = overlay_opts.get("text")
            
                        if not text:
                            with open(clip["path"], "rb") as f:
                                file_bytes = f.read()
                            text = generate_overlay_text_for_video(file_bytes)

                    normalize_and_overlay_clip(
                        clip["path"], out_path, is_image=False, duration=duration,
                        text=text,
                        fontcolor=overlay_opts.get("fontcolor", "white"),
                        fontsize=int(overlay_opts.get("fontsize", 46)),
                        position=overlay_opts.get("position", "center-bottom"),
                        animation=overlay_opts.get("animation", "static")
                    )
                else:
                    duration = max(MIN_IMAGE_DURATION, min(duration, MAX_IMAGE_DURATION))
                    out_path = clip["tmp"]
                    text = None
                    if overlay_enabled:
                        text = overlay_opts.get("text")
                        if not text:
                            with open(clip["path"], "rb") as f:
                                file_bytes = f.read()
                            text = generate_overlay_text_for_video(file_bytes)

                    normalize_and_overlay_clip(
                        clip["path"], out_path, is_image=True, duration=duration,
                        text=text,
                        fontcolor=overlay_opts.get("fontcolor", "white"),
                        fontsize=int(overlay_opts.get("fontsize", 46)),
                        position=overlay_opts.get("position", "center-bottom"),
                        animation=overlay_opts.get("animation", "static")
                    )

                normalized_clips.append(out_path)

            # Apply transitions
            final_video = os.path.join(temp_dir, "final_output.mp4")
            apply_transitions(normalized_clips, final_video, transition_type=opts.get("transition_type", "fade"))

            # Save & upload
            local_dir = os.path.join("media", "videos")
            os.makedirs(local_dir, exist_ok=True)
            filename = f"{request.user.username}_reel_{uuid.uuid4().hex[:6]}.mp4"
            local_path = os.path.join(local_dir, filename)
            shutil.copy(final_video, local_path)

            with open(final_video, 'rb') as f:
                video_bytes = f.read()
                        ##tring to generate_caption for the video ---14 october  -- working 
                generated_video_gcs_url = upload_file_to_gcs(bucket_name, video_bytes, "video")
                generated_video_signed_url =generate_signed_url(generated_video_gcs_url)
                caption_text = generate_caption(video_bytes, file_type="video")
                cleaned_text = clean_gemini_text(caption_text)   
                final_cleaned_data=cleaned_text +" " + "#MilanoCafe" + " "+ "#milanocafe_official"+" "+ "#milanocafe"
                

            ContentDB.objects.create(user=request.user,caption_text=final_cleaned_data, generated_video=generated_video_gcs_url)

            return Response({
                "success": True,
                "message": "Video generated successfully",
                "data": {"user": request.user.username,"generated_caption":final_cleaned_data, "generated_video": generated_video_signed_url},
                "error": False
            }, status=200)

        finally:
            shutil.rmtree(temp_dir)


### 25 sept 
#  making a 20 second video from a prompt + caption/hashtag
def generate_continuity_segments(raw_output):
    segment_prompts = []
    for line in raw_output.split("\n"):
        line = line.strip()
        # Keep lines that contain actual descriptive text
        if not line:
            continue
        # Skip lines that are just instructions or numbering text
        if line.lower().startswith("here are") or line.lower().startswith("segment"):
            continue
        # Remove numbering if present
        line = line.lstrip("0123456789. ").strip()
        # Add the line if it contains alphabetic characters (skip punctuation-only lines)
        if any(c.isalpha() for c in line):
            segment_prompts.append(line)

     # Always return exactly 3 segments
    if len(segment_prompts) < 3:
        segment_prompts += [segment_prompts[-1]] * (3 - len(segment_prompts))
    elif len(segment_prompts) > 3:
        segment_prompts = segment_prompts[:3]
    return segment_prompts

def merge_video_segments(segment_files, crossfade_duration=1, fps=30):
    """
    Merge video segments into a single video with crossfade and return video bytes.
    """
    clips = [VideoFileClip(f) for f in segment_files]
    clips = [clip.fx(audio_normalize) for clip in clips]

    final_clip = clips[0]
    for clip in clips[1:]:
        final_clip = concatenate_videoclips(
            [final_clip, clip], method="compose", padding=-crossfade_duration
        )
    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
        temp_path = temp_file.name
    final_clip.write_videofile(temp_path, fps=fps, codec="libx264")
    # Read file as bytes
    with open(temp_path, "rb") as f:
        video_bytes = f.read()
    # Cleanup
    for clip in clips:
        clip.close()
    for f in segment_files:
        os.remove(f)
        # print(f"🗑️ Deleted temp file: {f}")
    os.remove(temp_path)

    # print("🎉 Final video generated and converted to bytes")
    return video_bytes

class FullVideoGenerationAPI(APIView) :
    def post(self,request) :
        user=request.user
        prompt=request.data.get("prompt","")
        if not prompt :
            return Response({"success":False,"message":"prompt field is required","error":"False"})
        
        system_message = '''
You are an expert at creating consecutive video scene prompts. 
Take the user prompt  and split it into 3 sequential video segments, each 6-8 seconds long. 
Each segment should be a fully descriptive mini-prompt for video generation, including:
- Camera angle and movement
- Objects/characters (keep them consistent across segments)
- Environment details
- Lighting, mood, and cinematic style
Do NOT include numbering, labels, or any extra text. Each segment should be on its own line. Make sure all key objects and style remain consistent across all segments.
'''

        user_message = prompt
        response  = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[system_message, user_message] )

        raw_output = response.text
        segment_prompts = generate_continuity_segments(raw_output)
        
        segments_dict = {f"segment{i+1}": seg for i, seg in enumerate(segment_prompts)}
        # print("Generated Segment Prompts:", segments_dict)

       # Generate videos for each segment and save locally
        os.makedirs("./segments", exist_ok=True)
        segment_files = []
        for i, seg_prompt in enumerate(segment_prompts, start=1):
            filename = os.path.join("./segments", f"segment{i}.mp4")
            video_bytes = generate_video(seg_prompt)
            with open(filename, "wb") as f:
                f.write(video_bytes)
            # print(f"Saved video segment: {filename}")
            segment_files.append(filename)
       # Step 3: Merge videos → get bytes
        final_video_bytes = merge_video_segments(segment_files, crossfade_duration=1, fps=30)
        
        ##tring to generate_caption for the video ---14 october  -- working 
        caption_text = generate_caption(final_video_bytes, file_type="video")
        cleaned_text = clean_gemini_text(caption_text)   
        final_cleaned_data=cleaned_text +" " + "#MilanoCafe" + " "+ "#milanocafe_official"+" "+ "#milanocafe"
        # print(final_cleaned_data,"----------final_caption")


        # Step 4: Upload to GCS
        # video_gcs_url =None
        # final_video_url = None
        video_gcs_url = upload_file_to_gcs(bucket_name, final_video_bytes, "video")
        final_video_url =generate_signed_url(video_gcs_url)
        # print(final_video_url," --- video_url")
        content =ContentDB.objects.create(
            user=user,
            prompt_text = prompt,
            caption_text = final_cleaned_data,
            generated_video=video_gcs_url if video_gcs_url else None
        )   
        final_response ={
            "user" : content.user.username,
            "user_prompt": prompt,
            "generated_caption":final_cleaned_data,
            "generated_video" :final_video_url if final_video_url else None
        }

        return Response({
            "success":True,
            "message":"Video Generated Successfully",
            "response":final_response,
            "error":False
            },status=status.HTTP_200_OK)

### testing purpose
##fetching ontent for WeeklySelectedContent


class WeeklySelectionListAPI(generics.ListAPIView):
    queryset = WeeklySelection.objects.all()
    serializer_class = WeeklySelectionSerializer

 
 # Fetch all posts from a Facebook Page feed using page_id as query_parameter13oct
class FacebookFeedFetchView(APIView):
    """
    Fetch all posts from a Facebook Page feed.
    """
    permission_classes=[IsAuthenticated]
    def get(self, request):
        user=request.user
        page_id = request.query_params.get("page_id")
        if not page_id:
            return Response(
                {"success": False, "error": "Missing required query parameter: page_id"},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            page = MetaPageDB.objects.get(user=user, page_id=page_id)
            # print(page,"------------")
        except MetaPageDB.DoesNotExist:
            return Response(
                {"success": False, "error": f"No connected page found with page_id {page_id} for this user."},
                status=status.HTTP_404_NOT_FOUND
            )
        

        PAGE_ID=page.page_id 
        PAGE_ACCESS_TOKEN=page.page_access_token

        url = f"https://graph.facebook.com/v24.0/{PAGE_ID}/feed"
        params = {
            "fields": "id,message,created_time,attachments,permalink_url",
            "access_token": PAGE_ACCESS_TOKEN
        }
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            feed_data = response.json()
            return Response({"success": True, "feed": feed_data.get("data", [])})
        except requests.RequestException as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



########## Meta LoginAPIView and MetaCallbackAPIView14oct
'''
Meta Login & Callback

Added IsAuthenticated to MetaLoginAPIView → only logged-in users can connect Facebook/Instagram.
Used signed Django tokens (Signer) in state parameter → secure verification of the logged-in user.

In MetaCallbackAPIView:
Removed creation of a new user.
Retrieved existing logged-in user from signed token.
Saved long-lived access token in OAuthToken.
Fetched all Facebook pages managed by the user.
Fetched connected Instagram business accounts per page.
Stored all page info in MetaPageDB, supporting multiple pages per user.
'''

 
class MetaLoginAPIView(APIView):
    """
    Step 1: Returns the Meta OAuth login URL.
    Frontend redirects user to this URL to connect their account.
    """
    permission_classes=[IsAuthenticated]
    def get(self, request):
        provider = request.query_params.get("provider", "facebook")
        scope = (
            "business_management,pages_manage_posts,pages_show_list,"
            "pages_read_engagement,pages_manage_engagement,pages_manage_metadata,"
            "instagram_content_publish,instagram_basic,instagram_manage_insights"
        )

        redirect_uri = f"{BASE_URL}/api/auth/meta/callback/"
        signer = Signer()
        # Sign the user's token key to securely pass in state
        state = signer.sign(request.user.auth_token.key)
       

 
        auth_url = (
            f"https://www.facebook.com/v24.0/dialog/oauth?"
            f"client_id={META_APP_ID}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
            f"&response_type=code"
            f"&state={state}"
        )
        return Response({"success":True,"auth_url": auth_url,"error":False}, status=status.HTTP_200_OK)
 

 
class MetaCallbackAPIView(APIView):

    """
    Step 2: Meta redirects back here after login.
    Exchanges code for access_token, upgrades to long-lived token,
    fetches user info + all managed Pages + connected Instagram accounts,
    and stores them in the DB.
    """
    def get(self, request):
        code = request.query_params.get("code")
        state_token = request.query_params.get("state")
        if not code or not state_token:
            return Response({"error": "Missing code or state"}, status=400)

        redirect_uri = f"{BASE_URL}api/auth/meta/callback/"
        GRAPH_BASE_URL = "https://graph.facebook.com/v24.0"

        # --- Identify logged-in user via signed state ---
        signer = Signer()
        try:
            token_key = signer.unsign(state_token)
            token_obj = Token.objects.get(key=token_key)
            user = token_obj.user
        except Exception:
            return Response({"error": "Invalid state token"}, status=400)

        # --- Step 1: Exchange authorization code for short-lived token ---
        token_url = f"{GRAPH_BASE_URL}/oauth/access_token"
        res = requests.get(token_url, params={
            "client_id": META_APP_ID,
            "redirect_uri": redirect_uri,
            "client_secret": META_APP_SECRET,
            "code": code,
        })
        data = res.json()
        if "access_token" not in data:
            return Response({"error": "Token exchange failed", "details": data}, status=400)
        short_token = data["access_token"]

        # --- Step 2: Exchange short-lived token for long-lived token ---
        exchange_url = f"{GRAPH_BASE_URL}/oauth/access_token"
        exchange_res = requests.get(exchange_url, params={
            "grant_type": "fb_exchange_token",
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "fb_exchange_token": short_token,
        })
        long_data = exchange_res.json()
        access_token = long_data.get("access_token", short_token)
        expires_in = long_data.get("expires_in", 60 * 60 * 24 * 60)  # default ~60 days
   # --- Save OAuth token for the existing logged-in user ---
        oauth_token, _ = OAuthToken.objects.update_or_create(
            user=user,
            provider="meta",
            defaults={
                "access_token": access_token,
                "expires_at": timezone.now() + timedelta(seconds=expires_in),
            },
        )

        # --- Fetch all Facebook Pages ---
        pages_res = requests.get(f"{GRAPH_BASE_URL}/me/accounts", params={"access_token": access_token})
        pages_data = pages_res.json().get("data", [])
        pages_info = []

        for page in pages_data:
            page_id = page.get("id")
            page_name = page.get("name")
            page_access_token = page.get("access_token")

            # --- Fetch Instagram Business account ---
            instagram_id = None
            instagram_username = None
            try:
                details_res = requests.get(
                    f"{GRAPH_BASE_URL}/{page_id}",
                    params={
                        "fields": "instagram_business_account{username}",
                        "access_token": page_access_token,
                    },
                    timeout=15,
                )
                details_data = details_res.json()
                ig_info = details_data.get("instagram_business_account", {})
                if ig_info:
                    instagram_id = ig_info.get("id")
                    instagram_username = ig_info.get("username")
            except Exception:
                pass

            # --- Store page info in DB ---
            MetaPageDB.objects.update_or_create(
                user=user,
                page_id=page_id,
                defaults={
                    "oauth_token": oauth_token,
                    "page_name": page_name,
                    "page_access_token": page_access_token,
                    "instagram_business_id": instagram_id,
                    "instagram_username": instagram_username,
                },
            )

            pages_info.append({
                "page_id": page_id,
                "page_name": page_name,
                "page_access_token": page_access_token,
                "instagram_business_id": instagram_id,
                "instagram_username": instagram_username,
            })

        return Response({
            "message": "Meta account connected successfully!",
            "pages": pages_info,
        }, status=status.HTTP_200_OK)


### fetching page_id from db 
#### instagram- faceboook POst API

def post_facebook(user, page_id, media_type, media_url, caption=""):
    """
    Posts to a user's Facebook page.
    media_type: 'Post' (photo) or 'Reel' (video)
    """
    media_type = media_type.strip().capitalize()  # normalize input
    if media_type not in ["Post", "Reel"]:
        raise ValueError("media_type must be 'Post' or 'Reel'")

    # Fetch page info from DB
    try:
        page = MetaPageDB.objects.get(user=user, page_id=page_id)
    except MetaPageDB.DoesNotExist:
        raise Exception("Page not found for this user.")

    access_token = page.page_access_token
    params = {"access_token": access_token}

    if media_type == "Post":  # photo
        endpoint = f"https://graph.facebook.com/v24.0/{page_id}/photos"
        params["url"] = media_url
        if caption:
            params["caption"] = caption
        params["published"] = "true"
    else:  # Reel → video post
        endpoint = f"https://graph.facebook.com/v24.0/{page_id}/videos"
        params["file_url"] = media_url
        if caption:
            params["description"] = caption
        params["published"] = "true"

    res = requests.post(endpoint, data=params, timeout=30).json()
    if "error" in res:
        raise Exception(f"Facebook API Error: {res['error']}")

    return res.get("post_id") or res.get("id")


def post_instagram(user, page_id, media_url, caption="", media_type="Post"):
    """
    Posts to a user's Instagram Business account linked to a page.
    media_type: 'Post' (feed image) or 'Reel' (video reel)
    """
    media_type = media_type.strip().capitalize()
    if media_type not in ["Post", "Reel"]:
        raise ValueError("media_type must be 'Post' or 'Reel'")

    # Fetch page info from DB
    try:
        page = MetaPageDB.objects.get(user=user, page_id=page_id)
    except MetaPageDB.DoesNotExist:
        raise Exception("Page not found for this user.")

    ig_id = page.instagram_business_id
    if not ig_id:
        raise Exception("No Instagram business account connected for this page.")

    access_token = page.page_access_token
    params = {"access_token": access_token, "caption": caption}

    if media_type == "Reel":
        params["media_type"] = "REELS"
        params["video_url"] = media_url
    else:  # Post
        params["image_url"] = media_url

    # Create media container
    container_res = requests.post(f"https://graph.facebook.com/v24.0/{ig_id}/media", data=params).json()
    if "error" in container_res:
        raise Exception(f"Instagram Container Error: {container_res['error']}")
    container_id = container_res.get("id")

    # Wait until container is ready
    while True:
        status_res = requests.get(
            f"https://graph.facebook.com/v24.0/{container_id}?fields=status_code&access_token={access_token}"
        ).json()
        if status_res.get("status_code") == "FINISHED":
            break
        time.sleep(1)

    # Publish media
    publish_res = requests.post(
        f"https://graph.facebook.com/v24.0/{ig_id}/media_publish",
        data={"creation_id": container_id, "access_token": access_token}
    ).json()
    if "error" in publish_res:
        raise Exception(f"Instagram Publish Error: {publish_res['error']}")

    return publish_res.get("id")



##PSTReelDataAPI10oct
class FacebookPostAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            page_id = request.data.get("page_id")
            media_type = request.data.get("media_type")  # 'Post' or 'Reel'
            media_url = request.data.get("url")
            caption = request.data.get("caption", "")

            if not page_id or not media_type or not media_url:
                return Response(
                    {"success":False,"message": "page_id, media_type, and url are required","error":True},
                    status=status.HTTP_400_BAD_REQUEST
                )

            post_id = post_facebook(request.user, page_id, media_type, media_url, caption)
            return Response({"success": True, "post_id": post_id,"error":False})

        except Exception as e:
            return Response({"success": False,"message":str(e),"error": False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


###POSTRELLDATA INSTA09OCT
class InstagramPostAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            page_id = request.data.get("page_id")
            media_type = request.data.get("media_type", "Post")  # default to 'Post'
            media_url = request.data.get("url")
            caption = request.data.get("caption", "")

            if not page_id or not media_type or not media_url:
                return Response(
                    {"error": "page_id, media_type, and url are required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            post_id = post_instagram(request.user, page_id, media_url, caption, media_type)
            return Response({"success": True, "post_id": post_id,"error":False})

        except Exception as e:
            return Response({"success": False,"message":str(e),"error": True}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



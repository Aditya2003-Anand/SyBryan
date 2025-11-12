from django.shortcuts import render
from django.contrib.auth.models import User
from django.db.models import Q
from django.contrib.auth import authenticate, login, logout
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.signing import Signer
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated

from moviepy.editor import VideoFileClip, concatenate_videoclips, CompositeVideoClip, ColorClip, AudioFileClip, vfx
from moviepy.audio.fx.all import audio_normalize

from .serializers import ContentSerializer
from .models import ContentDB, MetaPageDB, OAuthToken, ScheduleContentDB,WeeklySelection

from google import genai
from google.genai import types
from google.cloud import storage
from google.cloud.exceptions import GoogleCloudError

from dotenv import load_dotenv

from PIL import Image, UnidentifiedImageError
from urllib.parse import urlparse
from io import BytesIO
from datetime import timedelta, datetime, date as dt_date
import os
import uuid
import base64
import requests
import re
import time
import tempfile
import shutil
from pathlib import Path
import subprocess
import librosa
import math
import json
import random
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail

load_dotenv()

GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
api_key = os.getenv('GEMINI_API_KEY')
bucket_name = os.getenv('bucket_name')
PROJECT_ID = os.getenv('project_id')
LOCATION = os.getenv('region')
client = genai.Client()
storage_client = storage.Client(project=PROJECT_ID)
META_APP_ID = os.getenv('META_APP_ID')
META_APP_SECRET = os.getenv('META_APP_SECRET')
BASE_URL = os.getenv('BASE_URL')
media_bucket_name = os.getenv("media_bucket_name")
creatomate_api_key = os.getenv('creatomate_api_key')
client_email = os.getenv('client_email')

# Register
class RegisterAPI(APIView):
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        first_name = request.data.get("first_name")
        last_name = request.data.get("last_name")
        email = request.data.get("email")

        if not username or not password or not first_name or not last_name or not email:
            return Response(
                {"success": False, "message": "All fields are required", "error": True},
                status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=username).exists():
            return Response(
                {"success": False, "message": "Username already exists", "error": True},
                status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email=email).exists():
            return Response(
                {"success": False, "message": "Email already exists", "error": True, },
                status=status.HTTP_400_BAD_REQUEST)
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
                    {"success": True, "message": "User successfully registered", "data": user_dict, "error": False},
                    status=status.HTTP_201_CREATED,
                )
        except Exception as e:
            return Response(
                {
                    "success": False, "message": "Unable to register user", "details": str(e), "error": True},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Login API
# function to login through username or email
def get_user(username):
    try:
        user = User.objects.filter(
            Q(email__iexact=username) | Q(username__iexact=username)
        ).first()
        return user
    except Exception as e:
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
                {"success": False, "message": "Invalid Credentials", "error": True},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user_data = authenticate(username=user.username, password=password)

        if not user_data:
            return Response(
                {"success": False, "message": "Invalid Credentials", "error": True, },
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
class LogoutAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"success": True, "message": "User Logged out successfully", "error": False})


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
        data = serializer.data
        for item in data:
            if item.get('generated_image'):
                item['generated_image'] = generate_signed_url(item['generated_image'])
            if item.get('uploaded_image'):
                item['uploaded_image'] = generate_signed_url(item['uploaded_image'])
            if item.get('generated_video'):
                item['generated_video'] = generate_signed_url(item['generated_video'])

        return Response({
            "success": True,
            "message": f"Content history for {user.username} fetched",
            "data": data,
            "error": False
        }, status=200)


# Fetch all contents on the db newest first
class ContentHistoryAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_data = ContentDB.objects.all().order_by('-created_at')
        serializer = ContentSerializer(query_data, many=True)
        data = serializer.data
        for item in data:
            if item.get('generated_image'):
                item['generated_image'] = generate_signed_url(item['generated_image'])
            if item.get('uploaded_image'):
                item['uploaded_image'] = generate_signed_url(item['uploaded_image'])
            if item.get('generated_video'):
                item['generated_video'] = generate_signed_url(item['generated_video'])
        return Response({
            "success": True,
            "message": "All Content History Fetched Successfully",
            "data": data,
            "error": False
        }, status=200)


class FetchContentAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        content = get_object_or_404(ContentDB, pk=pk)
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
            "uploaded_image": generate_signed_url(content.uploaded_image),
            "generated_image": generate_signed_url(content.generated_image),
            "generated_video": generate_signed_url(content.generated_video),
            "fb_post_id": content.fb_post_id,
            "ig_post_id": content.ig_post_id,
            "posted_to_fb": content.posted_to_fb,
            "posted_to_ig": content.posted_to_ig,
            "created_at": content.created_at,
            "updated_at": content.updated_at,
        }
        return Response(
            {"success": True, "message": f"Content with ID {pk} fetched successfully.", "data": data, "error": False},
            status=status.HTTP_200_OK)


def convert_http_to_gs(url: str) -> str:
    """
    Converts a Google Cloud Storage HTTP (signed or unsigned) URL
    back into its gs:// path.
    Examples:
        https://storage.googleapis.com/ai_field_bucket/images/img.png?X-Goog-...
        --> gs://ai_field_bucket/images/img.png

        https://storage.cloud.google.com/ai_field_bucket/videos/vid.mp4
        --> gs://ai_field_bucket/videos/vid.mp4
    """
    if not url or not isinstance(url, str):
        return url

    # Match both common GCS domains
    patterns = [
        r"https://storage\.googleapis\.com/([^/]+)/(.+)",
        r"https://storage\.cloud\.google\.com/([^/]+)/(.+)",
    ]

    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            bucket, path = match.groups()
            path = path.split("?")[0]  # remove query params
            return f"gs://{bucket}/{path}"
    # If it's already gs:// or a local file, leave unchanged
    return url


class ContentEditAPIView(APIView):
    """
    API to edit ContentDB items (caption, generated_image, generated_video).
    If the content has already been published in WeeklySelection and now changes have been made , reset posted flags
    so it can be republished.
    """
    permission_classes = [IsAuthenticated]

    def put(self, request, pk, format=None):
        content = get_object_or_404(ContentDB, pk=pk)
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

        generated_image = convert_http_to_gs(request.data.get("generated_image", content.generated_image))
        generated_video = convert_http_to_gs(request.data.get("generated_video", content.generated_video))

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
        if changed:
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
            message = f"Content with ID {pk} updated successfully (changes detected)."
        else:
            message = f"Content with ID {pk} updated successfully (no changes detected)."

        data = {
            "id": content.id,
            "caption_text": content.caption_text,
            "generated_image": generate_signed_url(content.generated_image),
            "generated_video": generate_signed_url(content.generated_video),
            "posted_to_fb": content.posted_to_fb,
            "posted_to_ig": content.posted_to_ig,
            "updated_at": content.updated_at,
        }
        return Response({
            "success": True,
            "message": message,
            "data": data,
            "error": False,
        }, status=status.HTTP_200_OK)


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
                "data": None,
                "error": True
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
    return gcs_path


def parse_gcs_uri(uri):
    parsed = urlparse(uri)
    if parsed.scheme != "gs":
        print(f"Skipping non-GCS path: {uri}")
        return None, None
    return parsed.netloc, parsed.path.lstrip('/')


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
    user_image_gcs_path = upload_file_to_gcs(bucket_name, image_bytes, file_type="image")
    user_image_signed_url = generate_signed_url(user_image_gcs_path, expiration_days=7)
    return image_bytes, mime_type, user_image_gcs_path, user_image_signed_url


def download_image_from_gcs(url):
    response = requests.get(url)
    if response.status_code == 200:
        return response.content, response.headers.get("Content-Type", "image/png")
    else:
        raise Exception("Failed to download image from GCS")


def generate_signed_url(gcs_path, expiration_days=7):
    if not gcs_path:
        return None
    bucket_name, object_name = parse_gcs_uri(gcs_path)
    if not bucket_name or not object_name:
        return None
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
            return signed_url
        time.sleep(2)

    raise RuntimeError("Blob does not exist in GCS after waiting.")


def generate_text(prompt):
    final_prompt = f"User query is: {prompt}. Respond to the user's query in a brief, concise, and meaningful way while ensuring clarity. Use complete sentences."
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=final_prompt
    )
    return response.text.strip()


def clean_gemini_text(text: str, escape_ffmpeg: bool = False) -> str:
    if not text:
        return ""
    # 1. Remove markdown/code artifacts
    text = re.sub(r'```[\w]*\n', '', text)  # opening code block
    text = re.sub(r'\n```', '', text)  # closing code block
    # 2. Remove excessive newlines
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    # 3. Strip leading/trailing whitespace
    text = text.strip()
    # 4. Optionally escape FFmpeg drawtext special characters
    if escape_ffmpeg:
        text = text.replace("'", r"'\''")  # single quote
        text = text.replace("\\", r"\\")  # backslash
        text = text.replace(":", r"\:")  # colon
        text = text.replace(",", r"\,")  # comma
    # 5. Normalize whitespace (spaces & newlines)
    text = re.sub(r'\s+', ' ', text)
    return text


def generate_caption(file_bytes, file_type):
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
    caption_text = response.text if hasattr(response, "text") else str(response)
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
        for part in response.candidates[0].content.parts:
            if part.text:
                generated_text = part.text
            elif part.inline_data:
                generated_image = Image.open(BytesIO(part.inline_data.data))
    return {"text": generated_text, "image": generated_image}


#  video
def generate_video(prompt=None, image_bytes=None, mime_type="PNG"):
    if not image_bytes:
        operation = client.models.generate_videos(
            model="veo-3.0-fast-generate-001",
            prompt=prompt)
    else:
        image_input = types.Image(
            image_bytes=image_bytes,
            mime_type=mime_type
        )
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
    return video_bytes


# VideoGeneration + caption/hastag
class VideoGenerationAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        prompt = request.data.get("prompt")
        image = request.FILES.get("image")
        if not prompt or not image:
            return Response({"success": False, "message": "both prompt and image fields are required", "error": True},
                            status=status.HTTP_400_BAD_REQUEST)

        user_image_gcs_url = user_image_signed_url = None
        if image:
            image_bytes, mime_type, user_image_gcs_url, user_image_signed_url = process_and_upload_image(image)
        generated_video_bytes = generate_video(prompt, image_bytes, mime_type)

        if generated_video_bytes:
            generated_video_gcs_url = upload_file_to_gcs(bucket_name, generated_video_bytes, file_type="video")
            generated_video_signed_url = generate_signed_url(generated_video_gcs_url)
        else:
            generated_video_gcs_url = generated_video_signed_url = None

        caption_text = generate_caption(generated_video_bytes, file_type="video")
        cleaned_text = clean_gemini_text(caption_text)
        final_cleaned_data = cleaned_text + " " + "#MilanoCafe" + " " + "#milanocafe_official" + " " + "#milanocafe"
        content = ContentDB.objects.create(
            user=user,
            prompt_text=prompt,
            caption_text=final_cleaned_data if final_cleaned_data else None,
            uploaded_image=user_image_gcs_url if user_image_gcs_url else None,
            generated_video=generated_video_gcs_url if generated_video_gcs_url else None
        )
        final_response = {
            "user": content.user.username,
            "user_prompt": prompt,
            "content_id": content.id,
            "generated_caption": final_cleaned_data,
            "uploaded_image": user_image_signed_url if user_image_signed_url else None,
            "generated_video": generated_video_signed_url if generated_video_signed_url else None
        }
        return Response(
            {"success": True, "message": "Generated Successfully", "response": final_response, "error": False},
            status=status.HTTP_200_OK)


class TextImageOverlayingAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        content_id = request.data.get("content_id", None)
        prompt = request.data.get("prompt", "").strip()
        image = request.FILES.get("image", None)
        if not image and content_id:
            try:
                prev_content = ContentDB.objects.get(id=content_id, user=user)
                prev_image_url = prev_content.generated_image or prev_content.uploaded_image
                prev_image_url = generate_signed_url(prev_image_url)
                print(prev_image_url, "---prev_image")
                if not prev_image_url:
                    return Response({
                        "success": False,
                        "message": "No previous image found for this content_id",
                        "error": True
                    }, status=status.HTTP_400_BAD_REQUEST)

                image_bytes, mime_type = download_image_from_gcs(prev_image_url)
                image = BytesIO(image_bytes)
            except ContentDB.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "Invalid content_id",
                    "error": True
                }, status=status.HTTP_400_BAD_REQUEST)

        if not image or not prompt:
            return Response({"success": False, "message": " both image  and prompt field is required", "error": True})

        final_prompt = f"""
            Use the uploaded image as the visual base and interpret the following user theme:
            "{prompt}"
            Create a **modern, social-media-ready promotional post** — like one designed by a professional content agency.
            It should feel polished, visually cohesive, and emotionally engaging — ready to post on Instagram or Facebook.
            ---
            ### 1. OBJECTIVE
            - The design should capture the **essence of the business or theme** (restaurant)
            - The text overlays must enhance the image — not distract from it — by blending naturally into the composition.
            - The end result should look like something a marketing agency would create for brand storytelling or promotions.
            ---
            ### 2. VISUAL STYLE
            - Use warm lighting, soft shadows, and subtle contrast to make the photo look premium.
            - Maintain **focus on the subject** — do not crop out key visual elements.
            - Apply a gentle vignette, depth-of-field blur, or gradient overlay if it helps the text readability.
            ---
            ### 3. TEXT OVERLAY DESIGN
            - Use clear **visual hierarchy**:
              - **Headline** (large, bold, serif or display font) — captures attention.
              - **Subheadline or Offer Line** (medium, sans-serif font) — gives context or value (e.g., “20% Off This Week”).
              - **Brand Tagline / Name / CTA** (smaller text, clean placement) — e.g., “Captured by SyBryan” or “Book Now”.
            - Combine **2–3 complementary fonts** (not all the same).
            - Ensure spacing, alignment, and scale follow modern ad layout standards.
            - Text colors should harmonize with the image: use light tones (ivory, gold, soft white) over dark areas or vice versa.
            - Avoid clutter, thick frames, or harsh bars; instead, use soft transparent overlays, gradients, or elegant shadows when needed.
            ---
            ### 4. BRAND STORYTELLING
            - The tone of the post should feel *authentic and cinematic* — like part of a real brand’s content library.
            - Include messaging that feels real to the setting — e.g., “Locally made”, “Limited Offer”, “Experience the vibe”, etc.
            - Emphasize *emotion and atmosphere* over literal description.
            ---
            ### 5. TEXT CONTENT OUTPUT
            - Create:
              - A short, brand-style caption (under 40 words)
              - 4–5 relevant hashtags.
            - Do **not** use emojis or meta language like “Here’s your caption”.
            ---
            ### 6. OUTPUT EXPECTATION
            - The final image must look **ready to post** — visually balanced, brand-consistent, and professionally designed.
            - Maintain a premium aesthetic similar to creative agency content that SyBryan would deliver to clients.
            """

        user_image_gcs_url = user_image_signed_url = None
        if image:
            image_bytes, mime_type, user_image_gcs_url, user_image_signed_url = process_and_upload_image(image)
            result = generate_image_text(final_prompt, image_bytes)
        else:
            result = generate_image_text(final_prompt)

        response_text = result.get("text")
        response_image = result.get("image")

        cleaned_text = clean_gemini_text(response_text)
        final_cleaned_data = cleaned_text + " " + "#MilanoCafe" + " " + "#milanocafe_official" + " " + "#milanocafe"
        print(final_cleaned_data, "----------final_caption")

        generated_image_gcs_url = generated_image_signed_url = None
        if response_image:
            img_bytes = BytesIO()
            response_image.save(img_bytes, format="PNG")
            img_bytes = img_bytes.getvalue()
            generated_image_gcs_url = upload_file_to_gcs(bucket_name, img_bytes, file_type="image")
            print(generated_image_gcs_url, "---db image url")
            generated_image_signed_url = generate_signed_url(generated_image_gcs_url)
            print(generated_image_signed_url, "------image url")

        content = ContentDB.objects.create(
            user=user,
            prompt_text=prompt,
            caption_text=final_cleaned_data if final_cleaned_data else None,
            uploaded_image=user_image_gcs_url if user_image_gcs_url else None,
            generated_image=generated_image_gcs_url if generated_image_gcs_url else None
        )
        final_response = {
            "user": content.user.username,
            "content_id": content.id,
            "generated_caption": final_cleaned_data,
            "uploaded_image": user_image_signed_url if user_image_signed_url else None,
            "generated_image": generated_image_signed_url if generated_image_signed_url else None
        }

        return Response(
            {"success": True, "message": "Generated Successfully", "response": final_response, "error": False},
            status=status.HTTP_200_OK)


# Imagegeneration+editing 0709 gcpdataset
def analyze_intent(prompt):
    system_prompt = """
    You are an AI that classifies user prompts related to image generation or editing.
    Return ONLY a valid JSON with this structure:
    {
        "intent": "edit" or "generate",
        "keywords": ["keyword1", "keyword2", ...]
    }
    Rules:
    - Intent is "edit" if user mentions changing, modifying, improving, enhancing, updating, or editing an image.
    - Intent is "generate" if user wants a new or fresh image.
    - Keep keywords short, relevant, lowercase.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part(text=system_prompt),
                types.Part(text=f"User prompt: {prompt}")
            ],
        )
        raw = getattr(response, "text", str(response))
        match = re.search(r"\{.*\}", raw, re.S)
        parsed = json.loads(match.group(0)) if match else {}
    except Exception as e:
        parsed = {"intent": "generate", "keywords": re.findall(r"\w+", prompt.lower())[:5]}
    intent = parsed.get("intent", "generate")
    keywords = parsed.get("keywords", [])
    return {"intent": intent, "keywords": keywords}


def fetch_image_gen(keywords, bucket_name, media_folder):
    image_url = None
    bucket = storage_client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=media_folder, max_results=300))
    if not blobs:
        print("⚠️ No images found in GCS folder.")
        return None

    # keyword based matching
    matched = [b for b in blobs if any(k in b.name.lower() for k in keywords)]
    # if not matched,randomly
    if not matched:
        matched = random.sample(blobs, 1)

    best_blob = random.choice(matched)
    image_gcs_path = f"gs://{bucket_name}/{best_blob.name}"

    signed_image_url = best_blob.generate_signed_url(version="v4", expiration=timedelta(days=2), method="GET")
    image_bytes, mime_type = download_image_from_gcs(signed_image_url)
    fetched_image_bytes = BytesIO(image_bytes)
    fetched_image_bytes.seek(0)
    image_bytes = fetched_image_bytes.getvalue()

    return {"image_bytes": image_bytes, "image_gcs_path": image_gcs_path, "signed_image_url": signed_image_url}


class ImageGenEditAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        prompt = request.data.get("prompt")
        content_id = request.data.get("content_id", "")
        user = request.user
        if not prompt:
            return Response({"success": False, "message": "Prompt is required", "error": True},
                            status=status.HTTP_400_BAD_REQUEST)
        # STEP 1: Analyze intent
        analysis = analyze_intent(prompt)
        intent = analysis["intent"]
        keywords = analysis["keywords"]
        prev_image_bytes = prev_image_url = prev_image_path = None

        if intent == "generate":
            print("Generating")
            # --- Fetch relevant GCS image ---
            fetched_data = fetch_image_gen(keywords, media_bucket_name, image_folder)
            if fetched_data:
                prev_image_bytes = fetched_data['image_bytes']
                prev_image_path = fetched_data['image_gcs_path']
                prev_image_url = fetched_data['signed_image_url']
                final_prompt = f"""
                    You are an AI image designer specializing in creating marketing visuals with **text overlays** and **real-world photographic bases**.
                    Never create abstract or generic generated backgrounds.
                    Use the uploaded image as the **visual base**, and interpret the following user theme:
                    "{prompt}"
                    Your goal is to design a **modern, social-media-ready promotional post** — like one created by a professional marketing agency.
                    The output should feel polished, emotionally engaging, and visually cohesive — ready to post directly on Instagram or Facebook.
                    --
                    ### 1. OBJECTIVE
                    - Build on the **existing photo** — do **not** replace it with a generic generated scene.
                    - Capture the **essence of the brand or business** (restaurant, cafe, lifestyle, etc.).
                    - Add text overlays that blend naturally with the composition — enhancing the image, not covering it.
                    - The final design should look like a real marketing post created for brand storytelling or promotions.
                    ---
                    ### 2. VISUAL STYLE
                    - Keep the original photo recognizable — do not distort or replace it.
                    - Use **warm, cinematic tones**, soft shadows, and balanced contrast for a premium look.
                    - Ensure **focus remains on the subject** — maintain clarity and composition.
                    - Apply subtle design touches (vignette, gradient overlay, gentle blur) only if they improve text readability.
                    - No heavy filters or frames — the design should look elegant and natural.
                    ---
                    ### 3. TEXT OVERLAY DESIGN
                    Follow a clear **visual hierarchy**:
                    - **Headline (bold, serif or display font):** captures attention with emotion or value.
                    - **Subheadline or Offer Line (medium, sans-serif):** gives context or incentive (e.g., “20% Off This Week”).
                    - **Brand Tagline / CTA / Signature (small text):** e.g., “Captured by SyBryan” or “Book Now”.
                    Design rules:
                    - Use 2–3 complementary fonts with good contrast.
                    - Ensure spacing, alignment, and scaling feel intentional and balanced.
                    - Text color must harmonize with the image — light tones (ivory, gold, soft white) over dark areas, or vice versa.
                    - Keep overlays minimal and integrated — use transparency or gradients to maintain realism.
                    - Always generate relevant text overlays unless explicitly instructed not to.
                    ---
                    ### 4. BRAND STORYTELLING
                    - The overall tone should feel *authentic, cinematic, and aspirational* — like part of a brand’s social feed.
                    - Use emotionally resonant copy — e.g., “Locally made”, “Taste the moment”, “Limited Time Offer”.
                    - Emphasize **mood and atmosphere** over literal description.
                    ---
                    ### 5. TEXT CONTENT OUTPUT
                    Produce:
                    - A **short, brand-style caption** (under 40 words).
                    - **4–5 relevant hashtags**.
                    Rules:
                    - No emojis.
                    - No meta text (e.g., “Here’s your caption”).
                    - Keep it in the same authentic, promotional tone as the overlay text.
                    ---
                    ### 6. OUTPUT EXPECTATION
                    - The final image should look **ready to post** — professionally designed, visually balanced, and brand-consistent.
                    - Maintain a premium aesthetic — something our creative agency would proudly deliver to a client.
                    """
                if not prev_image_bytes:
                    return Response(
                        {"success": False, "message": f"error occured while fetching from gcs '{image_folder}",
                         "error": True}, status=status.HTTP_404_NOT_FOUND)
                result = generate_image_text(final_prompt, prev_image_bytes)

        elif intent == "edit" and content_id:
            prev_content = ContentDB.objects.filter(id=content_id, user=user).first()
            if not prev_content:
                return Response({"success": False, "message": "Invalid content_id", "error": True},
                                status=status.HTTP_400_BAD_REQUEST)
            prev_image_path = prev_content.generated_image or prev_content.uploaded_image
            if not prev_image_path:
                return Response({"success": False, "message": "No image found for editing", "error": True},
                                status=status.HTTP_400_BAD_REQUEST)
            try:
                prev_image_url = generate_signed_url(prev_image_path, expiration_days=1)
                image_bytes, mime_type = download_image_from_gcs(prev_image_url)
                prev_image_bytes = BytesIO(image_bytes)
                prev_image_bytes.seek(0)
                image_bytes_data = prev_image_bytes.getvalue()
            except Exception as e:
                return Response({"success": False, "message": "Error fetching previous image", "error": str(e)},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            if image_bytes_data:
                final_prompt = f"""
                    You are a professional AI designer and image editor, capable of creatively interpreting edit instructions.

                    You are provided with:
                    1. A previously generated or uploaded **promotional-style image**.
                    2. The following **user instruction**: "{prompt}"
                    ---
                    ### 1. OBJECTIVE
                    - Apply the instruction confidently — interpret it visually and stylistically.
                    - You may modify **text overlays, design layout, colors, fonts, and composition** if it aligns with the user intent.
                    - Always preserve the **core concept and subject** — but you can restyle, recolor, or reposition design elements to refresh the look.
                    - Never output a blank or identical image; visible change must occur according to the instruction.
                    ---
                    ### 2. CREATIVE FREEDOM
                    - If the instruction is vague (e.g., “change the style”), use creative judgment to enhance the design:
                    - Experiment with new font pairings or color harmonies.
                    - Adjust text placement or layout.
                    - Enhance lighting or texture to elevate the composition.
                    - The goal is a **noticeable improvement or change**, while staying premium and professional.
                    ---
                    ### 3. VISUAL STYLE
                    - Maintain **balance and polish** — cinematic tones, natural lighting, and cohesive typography.
                    - Avoid artificial or stock-style looks.
                    - Blend any text or overlays naturally with the photo background.
                    ---
                    ### 4. BRAND CONSISTENCY
                    - Keep the **brand tone** warm, modern, and high-end.
                    - Reinforce the emotional feel of the image — cozy, festive, elegant, etc.
                    ---
                    ### 5. TEXT CONTENT OUTPUT
                    After editing, generate:
                    - A short caption (under 40 words) matching the new visual style.
                    - 4–5 relevant hashtags.
                    Rules:
                    - No emojis or meta language.
                    - Stay within a premium, brand-consistent tone.
                    ---
                    ### 6. OUTPUT EXPECTATION
                    - Always return a visually edited version of the provided image.
                    - The final image must look **professionally retouched, clearly updated, and ready to post.**
                    """

                result = generate_image_text(final_prompt, image_bytes_data)
        # fallback
        else:
            return Response({
                "success": False,
                "message": f"Unsupported intent '{intent}'. Expected 'generate' or 'edit'.You can either generate or edit the image.Nothing else",
                "error": True
            }, status=status.HTTP_400_BAD_REQUEST)

        # STEP 4: Extract results
        if not result:
            return Response({
                "success": False,
                "message": "Gemini response was empty or failed to generate output.",
                "error": True
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response_text = result.get("text", "")
        response_image = result.get("image", "")
        cleaned_caption = clean_gemini_text(response_text)
        caption_final = f"{cleaned_caption} #MilanoCafe #milanocafe_official #milanocafe"

        generated_image_gcs_url = generated_image_signed_url = None
        if response_image:
            img_bytes = BytesIO()
            response_image.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            generated_image_gcs_url = upload_file_to_gcs(bucket_name, img_bytes.getvalue(), file_type="image")
            generated_image_signed_url = generate_signed_url(generated_image_gcs_url)

        content = ContentDB.objects.create(
            user=user,
            prompt_text=prompt,
            caption_text=caption_final,
            uploaded_image=prev_image_path,
            generated_image=generated_image_gcs_url,
        )

        final_response = {
            "user": user.username,
            "content_id": content.id,
            "generated_caption": caption_final,
            "uploaded_image": prev_image_url,
            "generated_image": generated_image_signed_url,
        }

        return Response({
            "success": True,
            "message": "Generated successfully",
            "response": final_response,
            "error": False
        }, status=status.HTTP_200_OK)


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
                {"success": False, "message": "Please provide either an image file or an image URL, not both.",
                 "error": True},
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

        result = generate_image_text(final_prompt, image_bytes)
        response_text = result.get("text")
        response_image = result.get("image")
        cleaned_text = clean_gemini_text(response_text)
        final_cleaned_data = cleaned_text + " #MilanoCafe #milanocafe_official #milanocafe"
        print(final_cleaned_data, "----------final_caption")

        generated_image_gcs_url = generated_image_signed_url = None
        if response_image:
            img_bytes = BytesIO()
            response_image.save(img_bytes, format="PNG")
            img_bytes = img_bytes.getvalue()
            generated_image_gcs_url = upload_file_to_gcs(bucket_name, img_bytes, file_type="image")
            generated_image_signed_url = generate_signed_url(generated_image_gcs_url)

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

        return Response(
            {"success": True, "message": "Generated Successfully", "response": final_response, "error": False},
            status=status.HTTP_200_OK)


class ImageGenerationAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        prompt = request.data.get("prompt")

        if not prompt:
            return Response({"success": False, "message": "prompt field is required", "error": True},
                            status=status.HTTP_400_BAD_REQUEST)

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
        final_cleaned_data = cleaned_text + " " + "#MilanoCafe" + " " + "#milanocafe_official" + " " + "#milanocafe"

        generated_image_gcs_url = generated_image_signed_url = None
        if response_image:
            img_bytes = BytesIO()
            response_image.save(img_bytes, format="PNG")
            img_bytes = img_bytes.getvalue()
            generated_image_gcs_url = upload_file_to_gcs(bucket_name, img_bytes, file_type="image")
            generated_image_signed_url = generate_signed_url(generated_image_gcs_url)

            content = ContentDB.objects.create(
                user=user,
                prompt_text=prompt,
                caption_text=final_cleaned_data if final_cleaned_data else None,
                generated_image=generated_image_gcs_url if generated_image_gcs_url else None
            )
        final_response = {
            "user": content.user.username,
            "content_id": content.id,
            "generated_caption": final_cleaned_data,
            "generated_image": generated_image_signed_url if generated_image_signed_url else None
        }
        return Response(
            {"success": True, "message": "Generated Successfully", "response": final_response, "error": False},
            status=status.HTTP_200_OK)


FFMPEG_PATH = "/usr/bin/ffmpeg"
FFPROBE_PATH = "/usr/bin/ffprobe"
DEFAULT_MUSIC = os.path.join(settings.BASE_DIR, "media/audio/music.mp3")
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
    try:
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
    except genai.errors.ServerError as e:
        return ""  # Fallback text to allow video generation to continue
    except Exception as e:
        return ""
    overlay_text = response.text if hasattr(response, "text") else str(response)
    overlay_text = clean_gemini_text(overlay_text, escape_ffmpeg=True)
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
                text = clean_gemini_text(text, escape_ffmpeg=True)
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
                    drawtext = f"drawtext=text='{text}':fontcolor={fontcolor}:fontsize={fontsize}:{pos}:alpha='if(gt(t,{duration - 2}), ({duration}-t)/2,1)'"
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
                prev_duration = get_video_duration(clips[i - 1]) or 2
                offset = cumulative_time + prev_duration - TRANSITION_DURATION
                in1 = "[0:v]" if i == 1 else f"[v{i - 1}]"
                in2 = f"[{i}:v]"
                out_label = f"[v{i}]"
                filter_cmds.append(
                    f"{in1}{in2} xfade=transition={trans}:duration={TRANSITION_DURATION}:offset={offset} {out_label}")
                cumulative_time += prev_duration

            filter_complex = ";".join(filter_cmds)
            cmd = [
                FFMPEG_PATH, "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", f"[v{len(clips) - 1}]",
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

            with open(final_video, 'rb') as f:
                video_bytes = f.read()
                ##tring to generate_caption for the video ---14 october  -- working
                generated_video_gcs_url = upload_file_to_gcs(bucket_name, video_bytes, "video")
                generated_video_signed_url = generate_signed_url(generated_video_gcs_url)
                caption_text = generate_caption(video_bytes, file_type="video")
                cleaned_text = clean_gemini_text(caption_text)
                final_cleaned_data = cleaned_text + " " + "#MilanoCafe" + " " + "#milanocafe_official" + " " + "#milanocafe"

            ContentDB.objects.create(user=request.user, caption_text=final_cleaned_data,
                                     generated_video=generated_video_gcs_url)

            return Response({
                "success": True,
                "message": "Video generated successfully",
                "data": {"user": request.user.username, "generated_caption": final_cleaned_data,
                         "generated_video": generated_video_signed_url},
                "error": False
            }, status=200)

        finally:
            shutil.rmtree(temp_dir)


# 25 sept
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
    os.remove(temp_path)
    return video_bytes


class FullVideoGenerationAPI(APIView):
    def post(self, request):
        user = request.user
        prompt = request.data.get("prompt", "")
        if not prompt:
            return Response({"success": False, "message": "prompt field is required", "error": "False"})

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
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[system_message, user_message])

        raw_output = response.text
        segment_prompts = generate_continuity_segments(raw_output)

        segments_dict = {f"segment{i + 1}": seg for i, seg in enumerate(segment_prompts)}
        # Generate videos for each segment and save locally
        os.makedirs("./segments", exist_ok=True)
        segment_files = []
        for i, seg_prompt in enumerate(segment_prompts, start=1):
            filename = os.path.join("./segments", f"segment{i}.mp4")
            video_bytes = generate_video(seg_prompt)
            with open(filename, "wb") as f:
                f.write(video_bytes)
            segment_files.append(filename)
        final_video_bytes = merge_video_segments(segment_files, crossfade_duration=1, fps=30)

        caption_text = generate_caption(final_video_bytes, file_type="video")
        cleaned_text = clean_gemini_text(caption_text)
        final_cleaned_data = cleaned_text + " " + "#MilanoCafe" + " " + "#milanocafe_official" + " " + "#milanocafe"

        video_gcs_url = None
        final_video_url = None
        video_gcs_url = upload_file_to_gcs(bucket_name, final_video_bytes, "video")
        final_video_url = generate_signed_url(video_gcs_url)
        content = ContentDB.objects.create(
            user=user,
            prompt_text=prompt,
            caption_text=final_cleaned_data,
            generated_video=video_gcs_url if video_gcs_url else None
        )
        final_response = {
            "user": content.user.username,
            "user_prompt": prompt,
            "content_id": content.id,
            "generated_caption": final_cleaned_data,
            "generated_video": final_video_url if final_video_url else None
        }

        return Response({
            "success": True,
            "message": "Video Generated Successfully",
            "response": final_response,
            "error": False
        }, status=status.HTTP_200_OK)


class MetaLoginAPIView(APIView):
    """
    Step 1: Returns the Meta OAuth login URL.
    Frontend redirects user to this URL to connect their account.
    """
    permission_classes = [IsAuthenticated]

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
        return Response({"success": True, "auth_url": auth_url, "error": False}, status=status.HTTP_200_OK)


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


##24OCT2025for intentfeedgen
class AIContentGenerationAPI(APIView):
    permission_classes = [IsAuthenticated]

    TRANSITIONS = {
        "calm": [lambda c: c.fadein(1).fadeout(1), lambda c: c.crossfadein(1)],
        "energetic": [
            lambda c: c.set_position(lambda t: (-c.w + t * c.w, "center")),
            lambda c: c.fx(vfx.speedx, random.uniform(1.1, 1.4)),
            lambda c: c.fx(vfx.colorx, random.uniform(1.2, 1.4)),
        ],
        "emotional": [
            lambda c: c.fadein(1).fadeout(1),
            lambda c: CompositeVideoClip([ColorClip(c.size, (0, 0, 0), 0.5), c.set_start(0.5)]),
            lambda c: c.fx(vfx.resize, lambda t: 1 + 0.1 * t),
        ],
        "dark": [
            lambda c: CompositeVideoClip([ColorClip(c.size, (0, 0, 0), 0.5), c.set_start(0.5)]),
            lambda c: c.fx(vfx.lum_contrast, 0, 50, 128),
        ],
        "happy": [
            lambda c: c.fx(vfx.colorx, random.uniform(1.2, 1.4)),
            lambda c: c.fx(vfx.resize, lambda t: 1 + 0.1 * t),
            lambda c: c.fadein(1),
        ],
        "cinematic": [
            lambda c: c.crossfadein(1),
            lambda c: c.fx(vfx.resize, lambda t: 1 + 0.1 * t),
            lambda c: c.fx(vfx.lum_contrast, 0, 50, 128),
        ],
    }

    # ─── HELPER METHODS ───────────────────────────────
    def detect_intent(self, prompt):
        txt = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Classify as 'image' or 'video': {prompt}"
        ).text.lower()
        if "video" in txt:
            return "video"
        elif "image" in txt:
            return "image"
        return "unknown"

    def detect_mood(self, prompt):
        txt = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                f"Classify the mood of this prompt as one of: calm, energetic, emotional, dark, happy, cinematic. Prompt: {prompt}"]
        ).text.lower()
        for m in self.TRANSITIONS.keys():
            if m in txt:
                return m
        return "cinematic"

    def get_random_files(self, folder, count=1):
        blobs = list(storage_client.bucket(media_bucket_name).list_blobs(prefix=f"{folder}/"))
        if not blobs:
            return []
        return random.sample(blobs, min(len(blobs), count))

    def apply_transition(self, clip, mood):
        return random.choice(self.TRANSITIONS.get(mood, self.TRANSITIONS["cinematic"]))(clip)

    def merge_videos(self, video_blobs, mood):
        clips = []
        temp_files = []

        for blob in video_blobs:
            temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
            temp_files.append(temp_path)
            blob.download_to_filename(temp_path)
            clip = VideoFileClip(temp_path)
            clips.append(self.apply_transition(clip, mood))

        final_clip = concatenate_videoclips(clips, method="compose")

        # Optional background music
        music_path = os.path.join(settings.BASE_DIR, "media/audio/music.mp3")
        if os.path.exists(music_path):
            audio_clip = AudioFileClip(music_path).subclip(0, final_clip.duration)
            final_clip = final_clip.set_audio(audio_clip)

        # Save merged video to temp file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
            output_path = temp_file.name

        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac", threads=4, verbose=False,
                                   logger=None)
        final_clip.close()
        # Read file as bytes
        with open(output_path, "rb") as f:
            video_bytes = f.read()

        # Cleanup temp files
        for f in temp_files:
            os.remove(f)
        os.remove(output_path)
        return video_bytes

    # ─── POST METHOD ───────────────────────────────
    def post(self, request):
        user = request.user
        prompt = request.data.get("prompt")
        print("PROMPT :", prompt)
        if not prompt:
            return Response({"success": False, "message": "Prompt is required", "error": True}, status=400)
        intent = self.detect_intent(prompt)
        print("intent :", intent)
        if intent not in ["image", "video"]:
            return Response({"success": False, "message": "Could not determine intent", "error": True}, status=400)
        generated_video_gcs_url = generated_image_gcs_url = generated_image_signed_url = generated_video_signed_url = None

        # ─── IMAGE FLOW ─────────────────────
        if intent == "image":
            files = self.get_random_files("AdityaDatset_Images_1", 1)
            if not files:
                print("No image files found.")
                return
            blob = files[0]
            img_bytes = blob.download_as_bytes()
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
            result = generate_image_text(final_prompt, img_bytes)
            response_text = result.get("text")
            response_image = result.get("image")
            final_cleaned_data = clean_gemini_text(response_text) if response_text else ""
            final_cleaned_data += " #MilanoCafe #milanocafe_official #milanocafe"
            if response_image:
                img_bytes_io = BytesIO()
                response_image.save(img_bytes_io, format="PNG")
                img_bytes_io = img_bytes_io.getvalue()
                generated_image_gcs_url = upload_file_to_gcs(bucket_name, img_bytes_io, file_type="image")
                generated_image_signed_url = generate_signed_url(generated_image_gcs_url)
                print(generated_image_gcs_url, "----url")

        # ─── VIDEO FLOW ─────────────────────
        elif intent == "video":
            mood = self.detect_mood(prompt)
            files = self.get_random_files("AdityVideoDataSet", 2)
            if not files:
                return Response({"success": False, "message": "No videos found", "error": True}, status=404)
            print(f"{len(files)} files fetched")
            video_bytes = self.merge_videos(files, mood)
            print("video bytes", len(video_bytes))
            if video_bytes:
                generated_video_gcs_url = upload_file_to_gcs(bucket_name, video_bytes, file_type="video")
                generated_video_signed_url = generate_signed_url(generated_video_gcs_url)
                caption_text = generate_caption(video_bytes, file_type="video") if video_bytes else ""
                final_cleaned_data = clean_gemini_text(caption_text)
                final_cleaned_data += " #MilanoCafe #milanocafe_official #milanocafe"

        # ─── SAVE TO DB ─────────────────────
        content = ContentDB.objects.create(
            user=user,
            prompt_text=prompt,
            caption_text=final_cleaned_data if final_cleaned_data else None,
            generated_image=generated_image_gcs_url if generated_image_gcs_url else None,
            generated_video=generated_video_gcs_url if generated_video_gcs_url else None
        )

        final_response = {
            "user": user.username,
            "prompt": prompt,
            "content_id": content.id,
            "generated_caption": final_cleaned_data if final_cleaned_data else None,
            "generated_image": generated_image_signed_url if generated_image_signed_url else None,
            "generated_video": generated_video_signed_url if generated_video_signed_url else None
        }
        return Response(
            {"success": True, "message": "Generated Successfully", "response": final_response, "error": False},
            status=200)


###extend video length and text overlay28oct
# import os, random, tempfile, textwrap, time
# from django.conf import settings
# from moviepy.editor import (
#     VideoFileClip, AudioFileClip, concatenate_videoclips,
#     CompositeVideoClip, ImageClip, vfx, ColorClip
# )
# from PIL import Image, ImageDraw, ImageFont
# import numpy as np

# # ─── PIL-BASED TEXT OVERLAY ───────────────────────────────
# def create_text_overlay(text, size, duration):
#     W, H = size
#     img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
#     draw = ImageDraw.Draw(img)
#     font_size = int(H * 0.06)
#     try:
#         font = ImageFont.truetype("arial.ttf", font_size)
#     except:
#         font = ImageFont.load_default()

#     lines = textwrap.wrap(text, width=40)
#     y_text = H - int(H * 0.25)

#     for line in lines:
#         # ✅ Compatible text width/height calculation
#         try:
#             bbox = draw.textbbox((0, 0), line, font=font)
#             w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
#         except AttributeError:
#             # Fallback for older Pillow
#             w, h = draw.textsize(line, font=font)

#         draw.text(
#             ((W - w) / 2, y_text),
#             line,
#             font=font,
#             fill="white",
#             stroke_width=2,
#             stroke_fill="black"
#         )
#         y_text += h + 5

#     frame = np.array(img)
#     txt_clip = ImageClip(frame).set_duration(duration)
#     return txt_clip.set_position(("center", "bottom")).fadein(0.5).fadeout(0.5)


# # ─── MAIN API CLASS ───────────────────────────────
# class AIContentGenerationAPI(APIView):
#     permission_classes = [IsAuthenticated]

#     TRANSITIONS = {
#         "calm": [lambda c: c.fadein(1).fadeout(1)],
#         "energetic": [
#             lambda c: c.fx(vfx.speedx, random.uniform(1.1, 1.4)),
#             lambda c: c.fx(vfx.colorx, random.uniform(1.2, 1.4))
#         ],
#         "emotional": [lambda c: c.fadein(1).fadeout(1)],
#         "dark": [lambda c: c.fx(vfx.lum_contrast, 0, 50, 128)],
#         "happy": [lambda c: c.fx(vfx.colorx, random.uniform(1.2, 1.4))],
#         "cinematic": [
#             lambda c: c.crossfadein(1),
#             lambda c: c.fx(vfx.resize, lambda t: 1 + 0.1 * t)
#         ],
#     }

#     # ─── HELPERS ───────────────────────────────
#     def detect_intent(self, prompt):
#         txt = client.models.generate_content(
#             model="gemini-2.5-flash",
#             contents=f"Classify as 'image' or 'video': {prompt}"
#         ).text.lower()
#         if "video" in txt: return "video"
#         if "image" in txt: return "image"
#         return "unknown"

#     def detect_mood(self, prompt):
#         txt = client.models.generate_content(
#             model="gemini-2.5-flash",
#             contents=[f"Classify the mood as one of: calm, energetic, emotional, dark, happy, cinematic. Prompt: {prompt}"]
#         ).text.lower()
#         for m in self.TRANSITIONS.keys():
#             if m in txt:
#                 return m
#         return "cinematic"

#     def get_random_files(self, folder, count=1):
#         blobs = list(storage_client.bucket(media_bucket_name).list_blobs(prefix=f"{folder}/"))
#         if not blobs: return []
#         return random.sample(blobs, min(len(blobs), count))

#     def apply_transition(self, clip, mood):
#         return random.choice(self.TRANSITIONS.get(mood, self.TRANSITIONS["cinematic"]))(clip)

#     # ─── MERGE VIDEOS (PER-CLIP OVERLAY) ───────────────────────────────
#     def merge_videos(self, video_blobs, mood):
#         clips, temp_files = [], []

#         try:
#             for blob in video_blobs:
#                 # Download and load clip
#                 temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
#                 temp_files.append(temp_path)
#                 blob.download_to_filename(temp_path)
#                 clip = VideoFileClip(temp_path)
#                 clip = self.apply_transition(clip, mood)

#                 # Export small version to bytes for overlay text
#                 with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
#                     clip.write_videofile(tmp.name, codec="libx264", audio_codec="aac",
#                                          threads=4, verbose=False, logger=None)
#                     tmp.seek(0)
#                     file_bytes = tmp.read()
#                 os.remove(tmp.name)

#                 overlay_text = generate_overlay_text_for_video(file_bytes)
#                 cleaned_text=clean_gemini_text(overlay_text)
#                 if cleaned_text:
#                     txt_clip = create_text_overlay(cleaned_text, clip.size, clip.duration)
#                     clip = CompositeVideoClip([clip, txt_clip])
#                 clips.append(clip)

#             final_clip = concatenate_videoclips(clips, method="compose")

#             # Optional music
#             music_path = os.path.join(settings.BASE_DIR, "media/audio/music.mp3")
#             if os.path.exists(music_path):
#                 audio_clip = AudioFileClip(music_path).subclip(0, final_clip.duration)
#                 final_clip = final_clip.set_audio(audio_clip)

#             with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
#                 output_path = tmp.name
#             final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac",
#                                        threads=4, verbose=False, logger=None)
#             final_clip.close()
#             print("videos merged")
#             with open(output_path, "rb") as f:
#                 return f.read()

#         finally:
#             for f in temp_files:
#                 if os.path.exists(f): os.remove(f)
#             if 'output_path' in locals() and os.path.exists(output_path):
#                 os.remove(output_path)

#     # ─── POST METHOD ───────────────────────────────
#     def post(self, request):
#         try:
#             user = request.user
#             prompt = request.data.get("prompt")
#             if not prompt:
#                 return Response({"success": False, "message": "Prompt is required", "error": True}, status=400)

#             intent = self.detect_intent(prompt)
#             if intent not in ["image", "video"]:
#                 return Response({"success": False, "message": "Could not determine intent", "error": True}, status=400)

#             generated_image_gcs_url = generated_video_gcs_url = None
#             generated_image_signed_url = generated_video_signed_url = None
#             final_cleaned_data = ""

#             # ─── IMAGE FLOW ───────────────────────────────
#             if intent == "image":
#                 files = self.get_random_files("AdityaDatset_Images_1", 1)
#                 if not files:
#                     return Response({"success": False, "message": "No images found", "error": True}, status=404)
#                 blob = files[0]
#                 img_bytes = blob.download_as_bytes()
#                 # final_prompt = f"""{prompt}
#                 # Edit this image and write a catchy caption (no emojis, natural tone, relevant hashtags)."""
#                 final_prompt = f"""{prompt}
#             Edit the provided image based on the instructions.
#             Also, generate a concise social media caption for the edited image following these rules:
#             The caption must:
#             - Be a complete, natural sentence.
#             - Caption should be Uniques and more Engaging .
#             - Include relevant hashtags.
#             - Stay strictly within the context of the given image and prompt.
#             Do not:
#             - Use emojis.
#             - Add phrases like "Here's a caption for social media".
#             - Include unrelated details.
#             """
#                 result = generate_image_text(final_prompt, img_bytes)
#                 response_text = result.get("text", "")
#                 response_image = result.get("image")
#                 final_cleaned_data = clean_gemini_text(response_text) + " #MilanoCafe #milanocafe_official #milanocafe"
#                 if response_image:
#                     img_io = BytesIO()
#                     response_image.save(img_io, format="PNG")
#                     generated_image_gcs_url = upload_file_to_gcs(bucket_name, img_io.getvalue(), "image")
#                     generated_image_signed_url = generate_signed_url(generated_image_gcs_url)

#             # ─── VIDEO FLOW ───────────────────────────────
#             elif intent == "video":
#                 mood = self.detect_mood(prompt)
#                 files = self.get_random_files("AdityVideoDataSet", 3)
#                 if not files:
#                     return Response({"success": False, "message": "No videos found", "error": True}, status=404)

#                 video_bytes = self.merge_videos(files, mood)
#                 if video_bytes:
#                     generated_video_gcs_url = upload_file_to_gcs(bucket_name, video_bytes, "video")
#                     generated_video_signed_url = generate_signed_url(generated_video_gcs_url)
#                     caption_text = generate_caption(video_bytes, "video") if video_bytes else ""
#                     final_cleaned_data = clean_gemini_text(caption_text) + " #MilanoCafe #milanocafe_official #milanocafe"

#             # ─── SAVE TO DB ───────────────────────────────
#             content = ContentDB.objects.create(
#                 user=user,
#                 prompt_text=prompt,
#                 caption_text=final_cleaned_data or None,
#                 generated_image=generated_image_gcs_url,
#                 generated_video=generated_video_gcs_url,
#             )

#             response_data = {
#                 "user": user.username,
#                 "prompt": prompt,
#                 "content_id" :content.id,
#                 "generated_caption": final_cleaned_data or None,
#                 "generated_image": generated_image_signed_url,
#                 "generated_video": generated_video_signed_url,
#             }
#             return Response({"success": True, "message": "Generated Successfully", "response": response_data, "error": False}, status=200)

#         except Exception as e:
#             print("AIContentGenerationAPI Error:", e)
#             return Response({"success": False, "message": str(e), "error": True}, status=500)


# storing the uploaded file to  gcs
class UploadFileView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            uploaded_file = request.FILES.get("file")
            if not uploaded_file:
                return Response({
                    "success": False,
                    "message": "No file uploaded",
                    "error": True
                }, status=400)
            # Generate unique blob path
            blob_name = f"uploads/{uuid.uuid4()}_{uploaded_file.name}"
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            # Upload file directly to GCS
            blob.upload_from_file(
                uploaded_file.file,
                content_type=uploaded_file.content_type
            )
            return Response({
                "success": True,
                "message": "File uploaded successfully",
                "file_name": uploaded_file.name,
                "gcs_path": blob_name,
            })
        except GoogleCloudError as gce:
            # Handles GCS-specific errors (auth, network, permission)
            return Response({
                "success": False,
                "message": "Google Cloud Storage error.",
                "error": True,
                "details": str(gce)
            }, status=500)
        except Exception as e:
            return Response({
                "success": False,
                "message": "An unexpected error occurred during upload.",
                "error": True,
                "details": str(e)
            }, status=500)


# creatomate API's

def fetch_all_templates():
    url = "https://api.creatomate.com/v1/templates"
    headers = {"Authorization": f"Bearer {creatomate_api_key}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.RequestException as e:
        return {"success": False, "message": str(e), "data": []}

    templates = response.json()
    data = []
    for t in templates:
        data.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "tags": t.get("tags", []),
            "created_at": t.get("created_at"),
            "updated_at": t.get("updated_at"),
        })
    return {"success": True, "data": data}


def extract_editable_elements(elements):
    editable = []
    for el in elements:
        el_type = el.get("type")
        el_name = el.get("name")
        el_dynamic = el.get("dynamic", False)

        # ✅ Directly editable element
        if el_dynamic and el_name:
            if el_type == "text":
                editable.append({
                    "name": el_name,
                    "type": el_type,
                    "field": "text",
                    "current_value": el.get("text", "")
                })
            elif el_type in ["image", "video", "audio"]:
                editable.append({
                    "name": el_name,
                    "type": el_type,
                    "field": "source",
                    "current_value": el.get("source", "")
                })
        # 🔁 Recurse into sub-elements
        children = el.get("elements", [])
        if children:
            editable.extend(extract_editable_elements(children))
    return editable


def fetch_template_by_id(template_id):
    """
    Fetches a Creatomate template and returns its editable fields.
    """
    url = f"https://api.creatomate.com/v1/templates/{template_id}"
    headers = {"Authorization": f"Bearer {creatomate_api_key}"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.RequestException as e:
        return {
            "success": False,
            "message": f"Failed to fetch template details: {e}",
            "error": True
        }

    template = response.json()
    elements = template.get("source", {}).get("elements", [])
    editable_fields = extract_editable_elements(elements)
    response_data = {
        "success": True,
        "template_id": template.get("id"),
        "template_name": template.get("name"),
        "count": len(editable_fields),
        "editable_fields": editable_fields,
        "error": False
    }
    return response_data


def process_creatomate_render(user, template_id, modifications):
    """
    Handles the full Creatomate rendering → download → GCS upload → caption generation → DB save pipeline.
    Returns a dict with success flag, message, video URLs, and caption text.
    """

    CREATOMATE_URL = "https://api.creatomate.com/v2/renders"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {creatomate_api_key}",
    }
    payload = {
        "template_id": template_id,
        "modifications": modifications,
    }

    print(f"🎬 Starting Creatomate render for template: {template_id}")

    # Step 1️⃣: Trigger render
    try:
        render_response = requests.post(CREATOMATE_URL, json=payload, headers=headers)
        render_response.raise_for_status()
        render_info = render_response.json()
        render_id = render_info.get("id")
    except requests.RequestException as e:
        return {"success": False, "message": f"Creatomate render failed: {e}", "error": True}

    if not render_id:
        return {"success": False, "message": "Render ID not found in response", "error": True}

    print(f"⏳ Render job started. ID: {render_id}")

    # Step 2️⃣: Poll for completion
    max_wait = 120  # 2 minutes
    elapsed = 0
    video_url = None

    while elapsed < max_wait:
        try:
            status_response = requests.get(f"{CREATOMATE_URL}/{render_id}", headers=headers)
            status_response.raise_for_status()
            status_data = status_response.json()
            status_str = status_data.get("status")
        except requests.RequestException as e:
            return {"success": False, "message": f"Polling failed: {e}", "error": True}

        if status_str == "succeeded":
            video_url = status_data.get("url")
            print(f"✅ Render succeeded: {video_url}")
            break
        elif status_str == "failed":
            return {"success": False, "message": "Video rendering failed", "error": True}

        time.sleep(5)
        elapsed += 5
    else:
        return {"success": False, "message": "Render timed out after 5 minutes", "error": True}

    # Step 3️⃣: Download rendered video
    try:
        resp = requests.get(video_url)
        resp.raise_for_status()
        video_bytes = resp.content
        print(f"📥 Downloaded rendered video ({len(video_bytes)} bytes)")
    except requests.RequestException as e:
        return {"success": False, "message": f"Video download failed: {e}", "error": True}

    # Step 4️⃣: Upload to GCS + caption generation
    try:
        generated_video_gcs_url = upload_file_to_gcs(bucket_name, video_bytes, "video")
        caption_text = generate_caption(video_bytes, "video")
        final_caption = f"{clean_gemini_text(caption_text)} #MilanoCafe #milanocafe_official #milanocafe"
        print(f"📤 Uploaded to GCS: {generated_video_gcs_url}")
    except Exception as e:
        return {"success": False, "message": f"GCS upload or caption generation failed: {e}", "error": True}

    # Step 5️⃣: Save to DB
    try:
        content = ContentDB.objects.create(
            user=user,
            caption_text=final_caption or None,
            generated_video=generated_video_gcs_url
        )
    except Exception as e:
        return {"success": False, "message": f"Database save failed: {e}", "error": True}

    # Step 6️⃣: Return response
    response_data = {
        "success": True,
        "user": user.username,
        "content_id": content.id,
        "generated_caption": final_caption,
        "generated_video_url": video_url,
        "generated_video_gcs_path": generated_video_gcs_url,
        "error": False
    }

    print(f"🏁 Render pipeline completed successfully for user {user.username}")
    return response_data


# list all the templates in your project
class TemplateListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Fetch all templates from Creatomate
        """
        url = "https://api.creatomate.com/v1/templates"
        headers = {"Authorization": f"Bearer {creatomate_api_key}"}

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except requests.RequestException as e:
            return Response({
                "success": False,
                "message": f"Failed to fetch templates from Creatomate: {str(e)}",
                "error": True
            }, status=502)

        templates = response.json()
        data = []

        for t in templates:
            data.append({
                "id": t.get("id"),
                "name": t.get("name"),
                "tags": t.get("tags", []),
                "created_at": t.get("created_at"),
                "updated_at": t.get("updated_at"),
            })

        return Response({
            "success": True,
            "message": "All the templates fetched successfully",
            "count": len(data),
            "templates": data,
            "error": False
        }, status=200)


# Fetch template Details By ID
class TemplateDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, template_id):
        result = fetch_template_by_id(template_id)
        status_code = 200 if result.get("success") else 502
        return Response(result, status=status_code)


# create video
class RenderVideoAPIView(APIView):
    """
    API endpoint to render a video using Creatomate templates and assets stored in GCS.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        template_id = request.data.get("template_id")
        modifications = request.data.get("modifications", {})

        if not template_id:
            return Response({
                "success": False,
                "message": "template_id is required",
                "error": True
            }, status=status.HTTP_400_BAD_REQUEST)

        # Initialize GCS bucket
        bucket = storage_client.bucket(bucket_name)
        signed_modifications = {}

        # Convert GCS object paths to signed URLs (valid 15 min)
        for key, value in modifications.items():
            if isinstance(value, str) and value.startswith("uploads/"):
                blob = bucket.blob(value)
                try:
                    signed_url = blob.generate_signed_url(
                        version="v4",
                        expiration=timedelta(minutes=15),
                        method="GET",
                    )
                    signed_modifications[key] = signed_url
                except Exception as e:
                    return Response({
                        "success": False,
                        "message": f"Failed to generate signed URL for {value}",
                        "error": str(e)
                    }, status=500)
            else:
                signed_modifications[key] = value

        response_data = process_creatomate_render(request.user, template_id, modifications)

        return Response({
            "success": True,
            "message": "Video rendered, uploaded, and saved successfully.",
            "response": response_data,
            "error": False
        }, status=200)


class MetaConnectionStatusAPIView(APIView):
    """
    Check Meta (Facebook/Instagram) connection status for the logged-in user.
    - Verifies if Meta token exists.
    - Auto-refreshes token if expired or expiring soon.
    - Returns connected pages and Instagram accounts.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        GRAPH_BASE_URL = "https://graph.facebook.com/v24.0"

        # --- Step 1: Check for Meta OAuth token ---
        try:
            oauth = OAuthToken.objects.get(user=user, provider="meta")
        except OAuthToken.DoesNotExist:
            return Response({
                "success": True,
                "connected": False,
                "message": "Meta account not connected.",
                "pages": [],
            }, status=status.HTTP_200_OK)

        # --- Step 2: Check if token needs refresh ---
        remaining_time = (oauth.expires_at - timezone.now()).total_seconds()
        needs_refresh = remaining_time < (7 * 24 * 60 * 60)  # if less than 7 days left

        if oauth.expires_at < timezone.now():
            needs_refresh = True

        if needs_refresh:
            try:
                refresh_url = f"{GRAPH_BASE_URL}/oauth/access_token"
                res = requests.get(refresh_url, params={
                    "grant_type": "fb_exchange_token",
                    "client_id": META_APP_ID,
                    "client_secret": META_APP_SECRET,
                    "fb_exchange_token": oauth.access_token,
                }, timeout=15)
                data = res.json()
                new_token = data.get("access_token")
                expires_in = data.get("expires_in", 60 * 60 * 24 * 60)  # default ~60 days

                if new_token:
                    oauth.access_token = new_token
                    oauth.expires_at = timezone.now() + timedelta(seconds=expires_in)
                    oauth.save()
            except Exception as e:
                print("Meta token refresh failed:", str(e))

        # --- Step 3: Fetch all connected Pages & Instagram accounts ---
        pages = MetaPageDB.objects.filter(user=user)
        pages_data = [
            {
                "page_id": p.page_id,
                "page_name": p.page_name,
                "instagram_business_id": p.instagram_business_id,
                "instagram_username": p.instagram_username,
            }
            for p in pages
        ]

        # --- Step 4: Return structured response ---
        return Response({
            "success": True,
            "connected": True,
            "message": "Meta account connected.",
            "token_expires_at": oauth.expires_at,
            "pages": pages_data,
        }, status=status.HTTP_200_OK)


class InstagramAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]
    GRAPH_URL = "https://graph.facebook.com/v24.0"

    def get(self, request):
        user = request.user
        page_id = request.query_params.get("page_id")

        if not page_id:
            return Response({"success": False, "message": "Missing query parameter: page_id", "error": True},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            page = MetaPageDB.objects.get(user=user, page_id=page_id)
        except MetaPageDB.DoesNotExist:
            return Response({"success": False, "message": f"No connected page found with ID {page_id}", "error": True},
                            status=status.HTTP_404_NOT_FOUND)

        token = page.page_access_token
        ig_id = page.instagram_business_id

        if not ig_id:
            return Response({"success": False, "error": "No Instagram Business ID found for this page."},
                            status=status.HTTP_400_BAD_REQUEST)

        # ✅ Fetch recent media
        media_url = f"{self.GRAPH_URL}/{ig_id}/media"
        media_params = {
            "fields": "id,caption,media_type,timestamp",
            "limit": 25,
            "access_token": token,
        }

        try:
            media_res = requests.get(media_url, params=media_params, timeout=20)
            media_res.raise_for_status()
            posts = media_res.json().get("data", [])
        except Exception as e:
            return Response({"success": False, "message": f"Failed to fetch media: {str(e)}", "error": True},
                            status=status.HTTP_400_BAD_REQUEST)

        # ✅ For each post, fetch only essential insights
        analytics_data = []
        for post in posts:
            post_id = post.get("id")
            caption = post.get("caption", "")
            timestamp = post.get("timestamp")

            # Only key metrics
            metrics = "likes,comments,shares,reach"
            insights_url = f"{self.GRAPH_URL}/{post_id}/insights"
            params = {"metric": metrics, "access_token": token}

            try:
                res = requests.get(insights_url, params=params, timeout=20)
                res.raise_for_status()
                data = res.json()
                insights = self.process_insights(data)
            except Exception as e:
                insights = {"error": str(e)}

            likes = insights.get("likes", 0)
            comments = insights.get("comments", 0)
            shares = insights.get("shares", 0)
            reach = insights.get("reach", 0)

            # Engagement rate = (likes + comments + shares) / reach * 100
            try:
                engagement_rate = round(((likes + comments + shares) / reach) * 100, 1)
            except ZeroDivisionError:
                engagement_rate = 0.0

            analytics_data.append({
                "post_id": post_id,
                "caption": caption,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "reach": reach,
                "engagement_rate": f"{engagement_rate}%",
                "timestamp": timestamp,
            })

        return Response({"success": True, "instagram_page_id": ig_id, "instagram_page_name": page.instagram_username,
                         "data": analytics_data, "error": False}, status=status.HTTP_200_OK)

    def process_insights(self, data):
        """Convert IG insights JSON → flat dict."""
        if not data or "data" not in data:
            return {}
        insights = {}
        for metric in data.get("data", []):
            name = metric.get("name")
            values = metric.get("values", [])
            if values:
                insights[name] = values[-1].get("value")
        return insights


class FacebookAnalyticsView(APIView):
    """
    ✅ Fetch analytics for published Facebook posts and reels.
    Simplified structure, safe batch insights, Instagram-style response.
    """
    permission_classes = [IsAuthenticated]
    GRAPH_URL = "https://graph.facebook.com/v24.0"

    NORMAL_POST_METRICS = (
        "post_impressions,post_impressions_unique,post_engaged_users,"
        "post_clicks,post_reactions_by_type_total"
    )
    VIDEO_POST_METRICS = (
        "total_video_impressions,total_video_views,"
        "total_video_10s_views,total_video_avg_time_watched"
    )

    def get(self, request):
        user = request.user
        page_id = request.query_params.get("page_id")

        if not page_id:
            return Response({"success": False, "error": "Missing query parameter: page_id"}, status=400)

        # 🔹 Validate connected page
        try:
            page = MetaPageDB.objects.get(user=user, page_id=page_id)
        except MetaPageDB.DoesNotExist:
            return Response({"success": False, "error": f"No connected page found with ID {page_id}"}, status=404)

        token = page.page_access_token

        # 🔹 Get page name
        try:
            page_info = requests.get(
                f"{self.GRAPH_URL}/{page_id}",
                params={"fields": "name", "access_token": token},
                timeout=10
            ).json()
            page_name = page_info.get("name", "")
        except Exception:
            page_name = ""

        # 🔹 Fetch recent posts (reactions, comments, shares)
        feed_url = f"{self.GRAPH_URL}/{page_id}/feed"
        params = {
            "fields": (
                "id,message,created_time,permalink_url,"
                "attachments{media_type,media_url,title},"
                "reactions.summary(true).limit(0),"
                "comments.summary(true).limit(0),"
                "sharedposts.summary(true).limit(0)"
            ),
            "access_token": token,
            "limit": 25
        }

        try:
            feed_res = requests.get(feed_url, params=params, timeout=30)
            feed_res.raise_for_status()
            posts = feed_res.json().get("data", [])
        except Exception as e:
            return Response({"success": False, "error": f"Error fetching feed: {str(e)}"}, status=400)

        if not posts:
            return Response({
                "success": True,
                "page_id": page_id,
                "page_name": page_name,
                "posts": []
            }, status=200)

        # 🔹 Prepare batch insights requests
        batch_requests, post_map = [], {}
        for post in posts:
            post_id = post.get("id")
            attach = post.get("attachments", {}).get("data", [])
            attach_type = attach[0].get("media_type", "").lower() if attach else ""
            permalink = post.get("permalink_url", "")

            if "reel" in permalink.lower() or attach_type == "video":
                metrics = self.VIDEO_POST_METRICS
                endpoint = f"/{post_id}/video_insights"
            else:
                metrics = self.NORMAL_POST_METRICS
                endpoint = f"/{post_id}/insights"

            batch_requests.append({
                "method": "GET",
                "relative_url": f"{endpoint}?metric={metrics}"
            })

            post_map[post_id] = {
                "id": post_id,
                "message": post.get("message", ""),
                "created_time": post.get("created_time", ""),
                "permalink": permalink,
                "media_type": attach_type,
                "media_url": attach[0].get("media_url", "") if attach else "",
                "likes": post.get("reactions", {}).get("summary", {}).get("total_count", 0),
                "comments": post.get("comments", {}).get("summary", {}).get("total_count", 0),
                "shares": post.get("sharedposts", {}).get("summary", {}).get("total_count", 0),
            }

        # 🔹 Execute batch request for insights
        insights_data = self.execute_batch_requests(batch_requests, token)

        # 🔹 Combine post + insight data
        final_data = []
        for post_id, post in post_map.items():
            insight = insights_data.get(post_id, {})
            reach = insight.get("post_impressions_unique") or insight.get("total_video_impressions") or 0
            engaged = insight.get("post_engaged_users", 0)
            engagement_rate = round((engaged / reach) * 100, 2) if reach else 0

            final_data.append({
                "post_id": post_id,
                "caption": post["message"] or "Untitled Post",
                "likes": post["likes"],
                "comments": post["comments"],
                "shares": post["shares"],
                "reach": reach,
                "engagement_rate": f"{engagement_rate}%",
                "timestamp": post["created_time"]
            })

        return Response({
            "success": True,
            "page_id": page_id,
            "page_name": page_name,
            "posts": final_data
        }, status=200)

    # 🔹 Helper: Execute Facebook batch API
    def execute_batch_requests(self, batch_requests, token):
        results = {}
        if not batch_requests:
            return results

        for i in range(0, len(batch_requests), 50):
            chunk = batch_requests[i:i + 50]
            try:
                res = requests.post(
                    self.GRAPH_URL,
                    data={"access_token": token, "batch": json.dumps(chunk)},
                    timeout=40
                )
                res.raise_for_status()
                for idx, response in enumerate(res.json()):
                    post_id = chunk[idx]["relative_url"].split("/")[1]
                    if response.get("code") == 200:
                        data = json.loads(response["body"])
                        insights = {
                            m["name"]: m["values"][0]["value"]
                            for m in data.get("data", [])
                            if "values" in m
                        }
                        results[post_id] = insights
            except Exception:
                continue
        return results


class ScheduleContentAPIView(APIView):
    """
    Save scheduled content info to DB
    (Uploads file to Google Cloud Storage manually)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # === Extract request data ===
            content_type = request.data.get("content_type", "").strip().lower()
            platform = request.data.get("platform", "").strip().lower()
            caption = request.data.get("caption", "").strip()
            uploaded_file = request.FILES.get("file")
            date = request.data.get("date")
            time = request.data.get("time")
            # === Validation ===
            missing_fields = [
                field for field in ["content_type", "platform", "date", "time"]
                if not request.data.get(field)
            ]
            if missing_fields:
                return Response({"success": False, "message": f"Missing required fields: {', '.join(missing_fields)}",
                                 "error": True, }, status=status.HTTP_400_BAD_REQUEST)
            if not uploaded_file:
                return Response({"success": False, "message": f"Missing required field :file", "error": True, },
                                status=status.HTTP_400_BAD_REQUEST)

            if date:
                try:
                    date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"success": False, "message": "Invalid date format. Use YYYY-MM-DD.", "error": True},
                        status=status.HTTP_400_BAD_REQUEST)

                if date_obj < dt_date.today():
                    return Response(
                        {"success": False, "message": "Cannot schedule content in the past.", "error": True},
                        status=status.HTTP_400_BAD_REQUEST)
                date = date_obj  # ✅ overwrite with parsed date

            if time:
                try:
                    time = datetime.strptime(time, "%H:%M:%S").time()
                except ValueError:
                    return Response({"success": False, "message": "Invalid time format. Use HH:MM:SS.", "error": True},
                                    status=status.HTTP_400_BAD_REQUEST)

            if content_type not in ["post", "reel"]:
                return Response(
                    {"success": False, "message": "Invalid content_type.", "error": True},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if platform not in ["facebook", "instagram"]:
                return Response(
                    {"success": False, "message": "Invalid platform.", "error": True},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # === Upload file to GCS ===
            try:
                blob_name = f"uploads/{uuid.uuid4()}_{uploaded_file.name}"
                bucket = storage_client.bucket(bucket_name)
                blob = bucket.blob(blob_name)

                blob.upload_from_file(
                    uploaded_file.file,
                    content_type=uploaded_file.content_type,
                )

                # Store the GCS path, not a public URL
                uploaded_file_path = f"gs://{bucket_name}/{blob_name}"

            except Exception as e:
                return Response(
                    {
                        "success": False,
                        "message": "An unexpected error occurred during upload.",
                        "error": True,
                        "details": str(e),
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            # === Save to DB ===
            schedule = ScheduleContentDB.objects.create(
                user=request.user,
                file=uploaded_file_path,
                content_type=content_type,
                platform=platform,
                caption=caption,
                date=date,
                time=time,
            )

            # === Success Response ===
            return Response({
                "success": True,
                "message": "Content scheduled successfully.",
                "data": {
                    "id": schedule.id,
                    "file_url": schedule.file,
                    "content_type": schedule.content_type,
                    "platform": schedule.platform,
                    "caption": schedule.caption,
                    "status": schedule.status,
                    "date": schedule.date,
                    "time": schedule.time,
                    "created_at": schedule.created_at,
                },
                "error": False,
            },
                status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"success": False, "message": str(e), "error": True},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FetchScheduledQueueAPIView(APIView):
    """
    Retrieve all scheduled content for the authenticated user.
    Converts gs:// paths into signed HTTPS URLs.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            scheduled_items = ScheduleContentDB.objects.filter(user=user, status__iexact="scheduled").order_by(
                '-created_at')

            data = []
            for item in scheduled_items:
                signed_url = None
                if item.file:
                    try:
                        signed_url = generate_signed_url(item.file)
                    except Exception as e:
                        signed_url = None
                        print(f"⚠️ Failed to generate signed URL for {item.file}: {e}")

                data.append({
                    "id": item.id,
                    "file_url": signed_url,
                    "content_type": item.content_type,
                    "platform": item.platform,
                    "caption": item.caption,
                    "status": item.status,
                    "date": item.date,
                    "time": item.time,
                    "created_at": item.created_at,
                })

            return Response({
                "success": True,
                "message": f"Scheduled content for {user.username} fetched successfully.",
                "total": len(data),
                "scheduled_content": data,
                "error": False
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"success": False, "message": str(e), "error": True},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CancelScheduledContentAPIView(APIView):
    """
    Cancel a scheduled post before it's published.
    """
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        try:
            user = request.user

            # === Retrieve the scheduled post ===
            try:
                scheduled_post = ScheduleContentDB.objects.get(id=pk, user=user)
            except ScheduleContentDB.DoesNotExist:
                return Response(
                    {
                        "success": False,
                        "message": "Scheduled content not found or not authorized.",
                        "error": True,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            # === Validate status ===
            if scheduled_post.status.lower() != "scheduled":
                return Response(
                    {
                        "success": False,
                        "message": f"Cannot cancel. Current status is '{scheduled_post.status}'.",
                        "error": True,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # === Cancel the scheduled post ===
            scheduled_post.status = "cancelled"
            scheduled_post.save(update_fields=["status"])

            # === Success response ===
            return Response(
                {
                    "success": True,
                    "message": "Scheduled content cancelled successfully.",
                    "data": {
                        "id": scheduled_post.id,
                        "platform": scheduled_post.platform,
                        "caption": scheduled_post.caption,
                        "status": scheduled_post.status,
                        "date": scheduled_post.date,
                        "time": scheduled_post.time,
                    },
                    "error": False,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"success": False, "message": str(e), "error": True},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UpdateScheduledContentAPIView(APIView):
    """
    Update a scheduled post before it is published.
    """
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        try:
            user = request.user

            # === Retrieve scheduled content ===
            try:
                scheduled_post = ScheduleContentDB.objects.get(id=pk, user=user)
            except ScheduleContentDB.DoesNotExist:
                return Response(
                    {"success": False, "message": "Scheduled content not found or not authorized.", "error": True},
                    status=status.HTTP_404_NOT_FOUND
                )
            # === Only 'scheduled' posts can be edited ===
            if scheduled_post.status.lower() != "scheduled":
                return Response(
                    {"success": False, "message": f"Cannot edit. Current status is '{scheduled_post.status}'.",
                     "error": True},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # === Extract update fields ===
            uploaded_file = request.FILES.get("file")
            caption = request.data.get("caption")
            date = request.data.get("date")
            time = request.data.get("time")
            platform = request.data.get("platform")
            content_type = request.data.get("content_type")

            # === Validate platform & content type ===
            if platform and platform not in ["facebook", "instagram"]:
                return Response({"success": False, "message": "Invalid platform.", "error": True},
                                status=status.HTTP_400_BAD_REQUEST)

            if content_type and content_type not in ["post", "reel"]:
                return Response({"success": False, "message": "Invalid content_type.", "error": True},
                                status=status.HTTP_400_BAD_REQUEST)

            if date:
                try:
                    date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"success": False, "message": "Invalid date format. Use YYYY-MM-DD.", "error": True},
                        status=status.HTTP_400_BAD_REQUEST)

                if date_obj < dt_date.today():
                    return Response(
                        {"success": False, "message": "Cannot schedule content in the past.", "error": True},
                        status=status.HTTP_400_BAD_REQUEST)
                date = date_obj  # ✅ overwrite with parsed date

            if time:
                try:
                    time = datetime.strptime(time, "%H:%M:%S").time()
                except ValueError:
                    return Response({"success": False, "message": "Invalid time format. Use HH:MM:SS.", "error": True},
                                    status=status.HTTP_400_BAD_REQUEST)

            # Track if anything actually changed
            changes_made = False

            if uploaded_file:
                blob_name = f"uploads/{uuid.uuid4()}_{uploaded_file.name}"
                bucket = storage_client.bucket(bucket_name)
                blob = bucket.blob(blob_name)
                blob.upload_from_file(
                    uploaded_file.file,
                    content_type=uploaded_file.content_type
                )
                uploaded_file_path = f"gs://{bucket_name}/{blob_name}"
                scheduled_post.file = uploaded_file_path
                changes_made = True

            if caption is not None and caption != scheduled_post.caption:
                scheduled_post.caption = caption
                changes_made = True
            if date and str(date) != str(scheduled_post.date):
                scheduled_post.date = date
                changes_made = True
            if time and str(time) != str(scheduled_post.time):
                scheduled_post.time = time
                changes_made = True
            if platform and platform != scheduled_post.platform:
                scheduled_post.platform = platform
                changes_made = True
            if content_type and content_type != scheduled_post.content_type:
                scheduled_post.content_type = content_type
                changes_made = True

            if not changes_made:
                message = "No changes detected. Scheduled content remains unchanged."
            else:
                message = "Scheduled content updated successfully"
                scheduled_post.save()

            # === Generate signed URL ===
            file_url = None
            if scheduled_post.file:
                try:
                    file_url = generate_signed_url(scheduled_post.file)
                except Exception:
                    file_url = scheduled_post.file  # fallback to gs:// path

            return Response({
                "success": True,
                "message": message,
                "data": {
                    "id": scheduled_post.id,
                    "file_url": file_url,
                    "content_type": scheduled_post.content_type,
                    "platform": scheduled_post.platform,
                    "caption": scheduled_post.caption,
                    "status": scheduled_post.status,
                    "date": scheduled_post.date,
                    "time": scheduled_post.time,
                    "created_at": scheduled_post.created_at,
                },
                "error": False
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"success": False, "message": str(e), "error": True},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


###CreatomtaeAutomationAPI

from collections import defaultdict
from datetime import timedelta

image_folder = ""
video_folder = ""


# # Extract theme, keywords, and mood from user prompt
# def analyze_prompt(prompt_text: str):
#
#     system_prompt = """
# You are a helpful AI that extracts structured metadata from creative prompts.
# Return ONLY a valid JSON object with keys: theme, keywords (array), mood.
# """
#     user_prompt = f'User prompt: "{prompt_text}"'
#     try:
#         response = client.models.generate_content(
#             model="gemini-2.5-flash",
#             contents=types.Content(parts=[types.Part(text=system_prompt), types.Part(text=user_prompt)]),
#         )
#         raw = response.text if hasattr(response, "text") else str(response)
#         json_match = re.search(r"\{.*\}", raw, re.S)
#         parsed = json.loads(json_match.group(0)) if json_match else json.loads(raw)
#         return parsed
#     except Exception:
#         words = re.findall(r"\w+", prompt_text.lower())
#         return {"theme": prompt_text[:40], "keywords": words[:6], "mood": ""}


# 11Nov
def analyze_prompt(user_prompt: str):
    system_prompt = (
        "You are an assistant that analyzes short-form video creation prompts. "
        "Read the user prompt carefully and output a concise, comma-separated list "
        "of 5–10 tags that describe what the user wants in their video. "
        "Include tags for: video type (e.g. restaurant promo, travel vlog), "
        "media type (videos, images, or mix media), number of media elements if implied, "
        "style (e.g. smooth transitions, upbeat music, text overlay), and mood (e.g. positive, cinematic). "
        "Infer all of this from the user's wording. Return ONLY the tags, no explanations."
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=types.Content(parts=[
            types.Part(text=system_prompt),
            types.Part(text=user_prompt)
        ]),
    )
    raw_tags = response.text.strip().lower()
    tags = [t.strip() for t in raw_tags.replace("\n", ",").split(",") if t.strip()]
    return tags


from difflib import SequenceMatcher


def choose_best_template(user_tags, templates):
    """Fast + dynamic version – adds light random tie-breaking."""

    def sim(a, b):
        return SequenceMatcher(None, a, b).ratio()

    tag_text = " ".join(user_tags).lower()
    user_has_video = any(w in tag_text for w in ["video", "clip"])
    user_has_image = any(w in tag_text for w in ["image", "photo", "picture"])
    user_wants_mix = user_has_video and user_has_image or "mix" in tag_text

    best = {"tpl": None, "score": -1}
    tpl_tags=None
    for tpl in templates:
        tpl_tags = [t.lower() for t in tpl.get("tags", [])]
        if not tpl_tags:
            continue

        # semantic similarity
        score = sum(max(sim(u, t) for t in tpl_tags) for u in user_tags) / len(user_tags)

        tpl_str = " ".join(tpl_tags)
        tpl_has_video = any(w in tpl_str for w in ["video", "clip"])
        tpl_has_image = any(w in tpl_str for w in ["image", "photo", "picture"])

        # media penalties
        if user_wants_mix and not (tpl_has_video and tpl_has_image):
            score -= 0.2
        elif user_has_video and not tpl_has_video:
            score -= 0.1
        elif user_has_image and not tpl_has_image:
            score -= 0.05

        # small random jitter so close scores can swap occasionally
        score += random.uniform(-0.02, 0.02)

        if score > best["score"]:
            best = {"tpl": tpl, "score": score}

    tpl = best["tpl"]
    return {
        "template_id": tpl.get("id") if tpl else None,
        "template_name": tpl.get("name") if tpl else None,
        "template_tags": tpl.get("tags") if tpl else [],
        "score": round(best["score"], 3),
        "user_tags": user_tags,
    }


# AI chooses the best-fitting template from live Creatomate templates.
def choose_template_from_prompt(prompt_text: str, templates: list):
    """
    Choose the best template based on both name and tags using AI reasoning + fallback keyword overlap.
    """
    if not templates:
        return None

    # Build options string for AI
    options = "\n".join([
        f"{i + 1}. {t['name']} – tags: {', '.join(t.get('tags', []))}" for i, t in enumerate(templates)
    ])

    selection_prompt = f"""
    User request: "{prompt_text}"

    Available templates:
    {options}

    Choose ONE best-fitting template considering both name and tags.
    Return ONLY the EXACT template name from the list above — nothing else.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=types.Content(parts=[types.Part(text=selection_prompt)]),
        )
        text = response.text.lower()
        clean_text = re.sub(r"[^a-z0-9\s-]", "", text)

        # Try matching template name
        for t in templates:
            name_clean = re.sub(r"[^a-z0-9\s-]", "", t["name"].lower())
            if name_clean in clean_text or name_clean.split()[0] in clean_text:
                return t["id"]

        # Try matching by number if Gemini returns “Template 2”
        match = re.search(r"(\d+)", text)
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(templates):
                return templates[idx]["id"]

    except Exception as e:
        print(f"⚠️ AI selection failed: {e}")

    # 🧩 Fallback — keyword overlap using BOTH name + tags
    words = set(re.findall(r"\w+", prompt_text.lower()))

    def overlap_score(t):
        tokens = set(re.findall(r"\w+", (t["name"] + " " + " ".join(t.get("tags", []))).lower()))
        return len(words.intersection(tokens))

    best = max(templates, key=overlap_score, default=random.choice(templates))
    return best["id"]


def search_gcs(bucket_name, folder_prefix, keywords, max_results=10):
    """
    Search within a GCS folder for files that match given keywords in their names.
    Falls back to random selection if not enough matches are found.
    """
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=folder_prefix, max_results=200))
    except Exception:
        return []

    if not blobs:
        return []

    # Match by keyword relevance
    matched = [
        b for b in blobs
        if any(k.lower() in b.name.lower() for k in keywords)
    ]

    # If not enough relevant matches, mix in some random fallback
    if len(matched) < max_results:
        remaining = [b for b in blobs if b not in matched]
        random.shuffle(remaining)
        matched += remaining[:max_results - len(matched)]

    random.shuffle(matched)
    return matched[:max_results]


def fetch_relevant_media(keywords, num_images=0, num_videos=0):
    """
    Fetch relevant images and videos from GCS based on user prompt keywords.
    """
    try:
        images, videos = [], []
        if num_images > 0:
            images = search_gcs(media_bucket_name, image_folder, keywords, num_images)
        if num_videos > 0:
            videos = search_gcs(media_bucket_name, video_folder, keywords, num_videos)
    except Exception as e:
        pass

    return images, videos


def generate_overlay_text_cm_vid(file_bytes, file_type):
    """Generate short overlay text for an image or video."""
    if file_type == "video":
        mime_type = "video/mp4"
        prompt = """
Generate a short, catchy 3–8 word overlay text for this video. 
It should match the mood and visuals. No hashtags or emojis.
"""
    elif file_type == "image":
        mime_type = "image/png"
        prompt = """
Generate a short, catchy 3–8 word overlay text for this image.
It should match the context and vibe. No hashtags or emojis.
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=types.Content(
                parts=[
                    types.Part(inline_data=types.Blob(data=file_bytes, mime_type=mime_type)),
                    types.Part(text=prompt),
                ]
            ),
        )
        overlay_text = response.text.strip()
        return " ".join(overlay_text.split()[:8])
    except Exception:
        return ""


def pair_text_with_media(editable_fields):
    """
    Dynamically pairs text fields with image/video fields
    based on naming similarity (e.g. 'Photo-1' ↔ 'Details-1').
    Returns mapping: {media_field_name: [text_field_names]}
    """
    media_fields = [f for f in editable_fields if f["type"] in ("image", "video")]
    text_fields = [f for f in editable_fields if f["type"] == "text"]

    mapping = defaultdict(list)
    used_text = set()

    for media in media_fields:
        mname = media["name"].lower()
        match_num = re.findall(r"\d+", mname)
        related_texts = []
        for txt in text_fields:
            tname = txt["name"].lower()
            # Match by number or keyword similarity
            if any(n in tname for n in match_num) or any(k in tname for k in mname.split('-')):
                related_texts.append(txt["name"])
                used_text.add(txt["name"])
        mapping[media["name"]] = related_texts

    # Evenly distribute leftover text fields
    remaining_texts = [t["name"] for t in text_fields if t["name"] not in used_text]
    if remaining_texts and media_fields:
        for i, t in enumerate(remaining_texts):
            target_media = media_fields[i % len(media_fields)]
            mapping[target_media["name"]].append(t)

    return dict(mapping)


# Main API
class CMGenerateTemplateVideoAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_prompt = request.data.get("prompt")
        if not user_prompt:
            return Response({"success": False, "message": "prompt is required", "error": True}, status=400)

        # Step 1: Fetch templates
        templates_response = fetch_all_templates()
        if not templates_response["success"]:
            return Response(templates_response, status=502)
        templates = templates_response["data"]

        # Step 2: Analyze prompt → keywords & theme
        # ai_meta = analyze_prompt(user_prompt)
        # keywords = ai_meta.get("keywords", [])

        # Step 3: Choose best template
        # template_id = choose_template_from_prompt(user_prompt, templates)

        # 11 november
        keywords = analyze_prompt(user_prompt)
        best_template_result = choose_best_template(keywords, templates)
        template_id = best_template_result["template_id"]
        # ------------------

        # Step 4: Fetch template details
        fetched_result = fetch_template_by_id(template_id)
        if not fetched_result.get("success"):
            return Response(fetched_result, status=502)

        editable_fields = fetched_result["editable_fields"]
        image_fields = [f for f in editable_fields if f["type"] == "image"]
        video_fields = [f for f in editable_fields if f["type"] == "video"]
        text_fields = [f for f in editable_fields if f["type"] == "text"]

        # Step 5: Pair text fields with corresponding media fields
        text_mapping = pair_text_with_media(editable_fields)

        # Step 6: Fetch relevant assets
        images, videos = fetch_relevant_media(keywords, len(image_fields), len(video_fields))
        modifications = {}
        overlay_texts = []

        # Combine media in sequence for mapping
        all_media_fields = image_fields + video_fields
        all_media_blobs = images + videos

        for idx, media_field in enumerate(all_media_fields):
            if idx >= len(all_media_blobs):
                continue

            blob = all_media_blobs[idx]
            signed_url = blob.generate_signed_url(
                version="v4", expiration=timedelta(minutes=15), method="GET"
            )
            modifications[media_field["name"]] = signed_url

            # Generate overlay text(s) for this media
            related_texts = text_mapping.get(media_field["name"], [])
            file_bytes = blob.download_as_bytes()
            file_type = media_field["type"]

            for tfield in related_texts:
                try:
                    overlay_text = generate_overlay_text_cm_vid(file_bytes, file_type)
                    overlay_texts.append({tfield: overlay_text})
                    modifications[tfield] = overlay_text
                except Exception as e:
                    print(f"⚠️ Overlay text generation failed for {tfield}: {e}")

        # Step 7: Render final video
        response_data = process_creatomate_render(request.user, template_id, modifications)
        print({"ai_meta": ai_meta, "text_mapping": text_mapping, "overlay_texts": overlay_texts})

        return Response(response_data, status=status.HTTP_200_OK)


#########  reset email 11-11-2025
# User submits email → /password-reset/
# They receive a link → http://localhost:3000/reset-password/<uid>/<token>/
# Frontend shows password form.
# Submits new password → POST /password-reset-confirm/<uid>/<token>/
# API verifies token and resets password.




class PasswordResetRequestAPI(APIView):
    """
    Sends password reset link if: Email exists in system
    """

    def post(self, request):
        email = request.data.get("email")

        if not email:
            return Response({"success": False, "message": "Email is required", "error": True},
                            status=status.HTTP_400_BAD_REQUEST, )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"success": False, "message": "No user found with this email", "error": True},
                            status=status.HTTP_404_NOT_FOUND, )

        # Generate token + uid
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        #### user website address
        reset_link = f"http://34.63.46.227/reset-password/{uid}/{token}/"

        subject = "Password Reset Request"
        message = (
            f"Hi {user.first_name or user.username},\n\n"
            f"We received a request to reset your password for your Sybryan account.\n"
            f"You can reset your password securely by clicking the link below:\n\n"
            f"{reset_link}\n\n"
            f"If you didn’t request a password reset, please ignore this email. "
            f"Your account will remain secure.\n\n"
            f"Best regards,\n"
            f"The Sybryan Team\n"
            f"https://sybryan.com"
        )

        # ✅ Send email using settings.DEFAULT_FROM_EMAIL
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,  # Uses Gmail config automatically
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to send reset email", "error": True, "details": str(e), },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(
            {"success": True, "message": "Password reset link sent successfully", "data": {"reset_link": reset_link},
             "error": False}, status=status.HTTP_200_OK)


class PasswordResetConfirmAPI(APIView):
    """
    Allows setting a new password after verifying uid and token.
    """

    def post(self, request, uidb64, token):
        new_password = request.data.get("password")

        if not new_password:
            return Response(
                {"success": False, "message": "Password is required", "error": True},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return Response(
                {"success": False, "message": "Invalid reset link", "error": True},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify token (same as Django’s PasswordResetConfirmView)
        if not default_token_generator.check_token(user, token):
            return Response(
                {"success": False, "message": "Invalid or expired token", "error": True},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save()

        return Response(
            {"success": True, "message": "Password has been reset successfully", "error": False},
            status=status.HTTP_200_OK,
        )

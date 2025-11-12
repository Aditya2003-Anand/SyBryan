# SyBryan - AI Video Feed Project

## Overview
**SyBryan** is an AI-powered platform that allows users to generate engaging video reels and social media posts based on custom datasets (photos and videos). It integrates AI models to overlay text on images/videos, generate captions, and hashtags automatically.

The backend is built with ** REST Framework**, and it integrates with **Google Cloud Storage (GCS)** for media storage. AI content generation is handled using **Gemini AI models**.

---

## Features
- Generate image captions and hashtags automatically using AI.
- Generate video reels with custom datasets.
- Text overlaying on images/videos for social media optimization.
- Store uploaded media and generated content in Google Cloud Storage.
- User authentication and API access via Django REST Framework.
- Ready-to-integrate API endpoints for frontend UI.

---

## Technologies Used
- **Backend:** Python3.12, Django, Django REST Framework, REST API
- **AI Model:** Gemini 2.5 Flash (text & image generation), VEO3 
- **Storage:** Google Cloud Storage
- **Libraries:** Requests, Pillow, dotenv, schedule, Moviepy, FFMPEG
- **Deployment:** Nginx + Gunicorn on GCP

---

## API Endpoints

### 1. Registration API
**Endpoint:** `http://127.0.0.1:800/api/registration_api`  
**Method:** POST  
**Payload:**
```json
{
  "username": "test_user",
  "email": "testuser123@gmail.com",
  "password": "testuser@123",
  "first_name": "test",
  "last_name": "user"
}


import time
import logging
from urllib.parse import urlparse
from dotenv import load_dotenv
import os
from google import genai
from google.genai.types import GenerateVideosConfig
from google.cloud import storage
import os
load_dotenv()
logger = logging.getLogger(__name__)
 
api_key = os.getenv('GEMINI_API_KEY')
client = genai.Client()

PROJECT_ID = os.getenv('project_id')
LOCATION =os.getenv('region')
GCS_BUCKET_NAME =os.getenv('bucket_name')
 
print(PROJECT_ID,"\n",LOCATION,"\n",GCS_BUCKET_NAME)
 
# Set the path to your service account key JSON file
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] =  ""
if not PROJECT_ID or not GCS_BUCKET_NAME:
    raise EnvironmentError("Environment variables missing (GOOGLE_CLOUD_PROJECT or GCS_BUCKET_NAME)")
 
genai_veo_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
storage_client = storage.Client(project=PROJECT_ID)
 
def parse_gcs_uri(uri):
    parsed = urlparse(uri)
    if parsed.scheme != "gs":
        raise ValueError(f"Invalid GCS URI: {uri}")
    return parsed.netloc, parsed.path.lstrip('/')
 
def get_signed_gcs_url(bucket_name, object_name, expiration=3600):
    """Generate a signed URL to access the GCS object."""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(object_name)
 
    for _ in range(10):
        if blob.exists():
            return blob.generate_signed_url(version="v4", expiration=expiration)
        time.sleep(2)
 
    raise RuntimeError("Blob does not exist in GCS after waiting.")
 
def generate_video(prompt, aspect_ratio="16:9"):
    """Handles video generation and returns signed URL."""
    if not prompt:
        raise ValueError("Prompt is required")
 
    output_prefix = f"gs://{GCS_BUCKET_NAME}/generated_videos/{int(time.time())}"
    logger.info(f"Generating video with prompt: {prompt}")
 
    operation = genai_veo_client.models.generate_videos(
        model="veo-2.0-generate-001",
        prompt=prompt,

    )
 
    # Poll for completion
    timeout = 900
    poll_interval = 21
    start_time = time.time()
 
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise TimeoutError("Video generation timed out.")
 
        operation = genai_veo_client.operations.get(operation)
        if operation.done:
            break
        time.sleep(poll_interval)
 
    if operation.error:
        raise RuntimeError(f"Generation failed: {operation.error}")
 
    videos = operation.result.generated_videos
    if not videos:
        raise RuntimeError("No videos returned in the result.")
 
    video_uri = videos[0].video.uri
 
    bucket_name, object_name = parse_gcs_uri(video_uri)
    signed_url = get_signed_gcs_url(bucket_name, object_name)
 
    return {
        "video_url": signed_url,
        "message": "Video generated successfully"
    }
 
 

 
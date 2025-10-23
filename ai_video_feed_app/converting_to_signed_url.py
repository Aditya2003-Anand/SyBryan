

import time
import os
from dotenv import load_dotenv
from google.genai import types
from PIL import Image
from io import BytesIO
from google import genai
from google.cloud import storage



os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ""
api_key = os.getenv('GEMINI_API_KEY')
bucket_name=os.getenv('bucket_name')
PROJECT_ID = os.getenv('project_id')
LOCATION = os.getenv('region')

# client = genai.Client()
storage_client = storage.Client(project=PROJECT_ID)



from datetime import timedelta
import time
from urllib.parse import urlparse
storage_client = storage.Client(project=PROJECT_ID)



def parse_gcs_uri(uri):
    parsed = urlparse(uri)
    if parsed.scheme != "gs":
        raise ValueError(f"Invalid GCS URI: {uri}")
    return parsed.netloc, parsed.path.lstrip('/')


def generate_signed_url(gcs_path):
    bucket_name, object_name = parse_gcs_uri(gcs_path)
    blob = storage_client.bucket(bucket_name).blob(object_name)

   # Retry until blob exists or timeout
    retries = 10
    for _ in range(retries):
        if blob.exists():
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(days=7)
            )
            expiration_td = timedelta(days=7)
            print(f"\n\n DEBUG: Expiration timedelta set to: {expiration_td}\n\n")

            print(signed_url, "-> Signed URL of uploaded file")
            return signed_url
        time.sleep(2)

    raise RuntimeError("Blob does not exist in GCS after waiting.")


# generate_signed_url(gcs_path)
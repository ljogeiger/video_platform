import streamlit as st
from google.cloud import aiplatform_v1
from google.cloud import storage
import vertexai,io
import json
import math
from vertexai.generative_models import GenerativeModel, Part
from st_files_connection import FilesConnection

from vertexai.vision_models import (
    MultiModalEmbeddingModel,
    MultiModalEmbeddingResponse,
)

PROJECT_ID = "videosearch-cloudspace"
REGION = "us-central1"
API_ENDPOINT="1949003250.us-central1-6255484976.vdb.vertexai.goog"
INDEX_ENDPOINT="projects/6255484976/locations/us-central1/indexEndpoints/4956743553549074432"
DEPLOYED_INDEX_ID="video_search_endpoint_1710342048921"
DEPLOYED_ENDPOINT_DISPLAY_NAME = "Video Search Endpoint"
VIDEO_SOURCE_BUCKET = "videosearch-source-videos"
TOP_N = 4
EMBEDDINGS_BUCKET = "videosearch-embeddings"

# Define storage client for file uploads
storage_client = storage.Client(project=PROJECT_ID)


# Function to display videos in N columns
def columnize_videos(result_list, num_col = 2):
  cols = st.columns(num_col)
  try:
    for row in range(math.ceil(len(result_list) / num_col)):
      for col in range(num_col):
        item = row * num_col + col
        cols[col].text(result_list[item]["result"])
        cols[col].video(result_list[item]["temp_file_name"], start_time=result_list[item]["start_sec"])
        cols[col].text(f"Distance: {result_list[item]['distance']:.4f}")
  except IndexError as e:
     print(f"Index out of bounds: {e}")
  return


# Function to parse findNeighbors result
# OUT: list of neighbor dicts
def parse_neighbors(neighbors):
  videos = []
  for n in range(len(neighbors)):
    start_sec = (int(neighbors[n].datapoint.datapoint_id.split("_")[-1]) - 1) * 5 # 16 because that's the default split on multimodal embeddings api
    video_name = "_".join(neighbors[n].datapoint.datapoint_id.split("_")[:-1])
    temp_file_name = f"/tmp/temp-{n}.mp4"

    with open(f'{temp_file_name}','wb') as file_obj:
      storage_client.download_blob_to_file(f'gs://videosearch_video_source_parts/{video_name}',file_obj)
    d = {
      "result" : f"Result #{n+1}\nTimestamps:{start_sec}->{start_sec+5}\n{neighbors[n].datapoint.datapoint_id}", #5 because that's what I set IntervalSec in embeddings api call
      "file": f"{neighbors[n].datapoint.datapoint_id}",
      "temp_file_name" : temp_file_name,
      "start_sec": start_sec,
      "distance": neighbors[n].distance,
    }
    videos.append(d)
  return videos


# Function to upload bytes object to GCS bucket
def upload_video_file(uploaded_file, bucket_name):

  bucket = storage_client.bucket(bucket_name)
  blob = bucket.blob(uploaded_file.name)
  blob.upload_from_string(uploaded_file.read())

  st.write("Upload Successful")

  return



st.title("FakeCompany - Video Platform")

st.text("""
        Welcome to FakeCompany's Video Platform!
        This application is meant to be you're go to destination for all
        your video needs. Here are some things you can do:

          1. Similarity search through all videos in FakeCompany's database
          2. Summarize video
          3. Generate analytical article based on video
          4. Ask questions of video
        """)

st.header("Similarity search through all videos in FakeCompany's database")


# Perform upload

uploaded_file = st.file_uploader("Choose a video...", type=["mp4"])
upload_file_start = st.button("Upload File")

if upload_file_start:
    upload_video_file(uploaded_file=uploaded_file, bucket_name="videosearch_source_videos")

#Search

query = st.text_input("Video Search", key="query")
search_button = st.button("Search")

if search_button:
  # Get embeddings from query
  model = MultiModalEmbeddingModel.from_pretrained(
      model_name="multimodalembedding@001"
      )

  embedding = model.get_embeddings(
      contextual_text=query
  )
  query_embedding = embedding.text_embedding

  # Perform search

  client_options = {
    "api_endpoint": API_ENDPOINT
  }

  vector_search_client = aiplatform_v1.MatchServiceClient(
    client_options=client_options,
  )

  # Build FindNeighborsRequest object
  datapoint = aiplatform_v1.IndexDatapoint(
    feature_vector=query_embedding
  )
  query = aiplatform_v1.FindNeighborsRequest.Query(
    datapoint=datapoint,
    # The number of nearest neighbors to be retrieved
    neighbor_count=TOP_N
  )
  request = aiplatform_v1.FindNeighborsRequest(
    index_endpoint=INDEX_ENDPOINT,
    deployed_index_id=DEPLOYED_INDEX_ID,
    # Request can have multiple queries
    queries=[query],
    return_full_datapoint=False,
  )

  # Execute the request
  response = vector_search_client.find_neighbors(request)

  # Parse the response object
  neighbors = response.nearest_neighbors[0].neighbors
  result_list = parse_neighbors(neighbors)

  # Display content
  columnize_videos(result_list, num_col = 2)

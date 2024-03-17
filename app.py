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

# My Gemini 1.5 Pro model is in a different project.
# Need to init on geminipro1-5 project in Argolis
with st.sidebar:
  model_selection = st.radio(
    "Which Gemini model?",
    options = ["Gemini Pro Vision 1.0", "Gemini Pro Vision 1.5"],
    captions = ["","Rate limited at 5 QPM"]
    )

# Logic to select the model. Gemini 1.5 is in different project
# will access video objects from gs://geminipro15-video-source-parts
# Cloud Function uploads video parts to both buckets
if model_selection == "Gemini Pro Vision 1.5":
  vertexai.init(project="geminipro1-5", location="us-central1")
  model_gem = GenerativeModel("gemini-1.5-pro-preview-0215")
elif model_selection == "Gemini Pro Vision 1.0":
  vertexai.init(project="videosearch-cloudspace", location="us-central1")
  model_gem = GenerativeModel("gemini-1.0-pro-vision-001")

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
def parse_neighbors(_neighbors):
  videos = []
  for n in range(len(neighbors)):
    start_sec = (int(neighbors[n].datapoint.datapoint_id.split("_")[-1]) - 1) * 5 # 5 because I set IntervalSecs on Embeddings API to 5. We generate an embedding vector for each 5 second interval
    video_name = "_".join(neighbors[n].datapoint.datapoint_id.split("_")[:-1]) # files stored in 2 minute segements in GCS
    print(f"Downloading - Video Name: {video_name}")
    print(f"Downloading - File Name: {neighbors[n].datapoint.datapoint_id}")
    temp_file_name = f"/tmp/temp-{n}.mp4"

    with open(f'{temp_file_name}','wb') as file_obj:
      storage_client.download_blob_to_file(f'gs://videosearch_video_source_parts/{video_name}',file_obj)

    d = {
      "result" : f"Result #{n+1}\nTimestamps:{start_sec}->{start_sec+5}\n{neighbors[n].datapoint.datapoint_id}", #5 because that's what I set IntervalSec in embeddings api call
      "gcs_file": f"{video_name}",
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

# Function to get embedding from query text
def get_query_embedding(query):
  model = MultiModalEmbeddingModel.from_pretrained(
      model_name="multimodalembedding@001"
      )

  embedding = model.get_embeddings(
      contextual_text=query
  )
  query_embedding = embedding.text_embedding
  return query_embedding


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

result_list = []

if search_button and query:
  print(query)
  # Get embeddings from query
  query_embedding = get_query_embedding(query)

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
  datapoint_query = aiplatform_v1.FindNeighborsRequest.Query(
    datapoint=datapoint,
    # The number of nearest neighbors to be retrieved
    neighbor_count=TOP_N
  )
  request = aiplatform_v1.FindNeighborsRequest(
    index_endpoint=INDEX_ENDPOINT,
    deployed_index_id=DEPLOYED_INDEX_ID,
    # Request can have multiple queries
    queries=[datapoint_query],
    return_full_datapoint=False,
  )

  # Execute the request
  response = vector_search_client.find_neighbors(request)

  # Parse the response object
  neighbors = response.nearest_neighbors[0].neighbors
  result_list = parse_neighbors(neighbors)

  st.session_state["neighbor_result"] = result_list

  # Display content
  columnize_videos(result_list, num_col = 2)

st.header("Summarize video")
st.text("Click one of the buttons below to summarize the video.\nPro 1.5 will take timestamps into account. Pro 1.0 will not.")

if "neighbor_result" in st.session_state:
  neighbors = st.session_state["neighbor_result"] # need to store in session state because otherwises it's not accessible

  buttons_summarize = []
  for i in range(TOP_N):
    buttons_summarize.append(st.button(f"Summarize Video {neighbors[i]['result']}"))

  for i, button_summarize in enumerate(buttons_summarize):
    if button_summarize:
      # objects live in seperate projects because the models are in different projects
      if model_selection == "Gemini Pro Vision 1.5":
        prompt_summarize = f"""
        Summarize the following video. Only mention items that occur in the video.
        Limit the summarization to the events that occur between start and end timestamps.

        Start:{neighbors[i]['start_sec']} seconds
        End: {neighbors[i]['start_sec']+5} seconds

        {query} might be seen or relate to events between the start and end timestamps. If it does, explain how.
        """
        gcs_uri_summarize = f"gs://geminipro-15-video-source-parts/{neighbors[i]['gcs_file']}"
      elif model_selection == "Gemini Pro Vision 1.0": #TODO: sometimes only responds "good"
        prompt_summarize = f"Your job is to summarize the following video. Only mention events and items that occur in the video. Include an answer to the following question: Where does {query} surface in the video?"
        gcs_uri_summarize = f"gs://videosearch_video_source_parts/{neighbors[i]['gcs_file']}"

      print(gcs_uri_summarize)
      input_file_summarize = [
        Part.from_uri(uri = gcs_uri_summarize, mime_type="video/mp4"),
        prompt_summarize
        ]
      print(input_file_summarize)
      response_summarize = model_gem.generate_content(input_file_summarize,
                                            generation_config={
                                              "max_output_tokens": 2048,
                                              "temperature": 0.3,
                                              "top_p": 0.4
                                            })
      st.write(response_summarize.text)
      st.write(f"{i+1} button was clicked")

st.header("Generate article from video")
st.text("Click one of the buttons below to generate an article from the video.")

if "neighbor_result" in st.session_state:
  neighbors = st.session_state["neighbor_result"] # need to store in session state because otherwises it's not accessible

  # Allow the user to modify the prompt
  if model_selection == "Gemini Pro Vision 1.5":
        prompt_generate = f"""
        You are a journalist. Your job is to write an article with the provided video as your source.
        Make sure to ground your article only to events occurred in the video.
        If you reference a part of the video you must provide a timestamp.

        In the article, make sure to include:
         1. A summary of what happened in the video.
         2. Your interpretation of events.
         3. Analysis of why these events occurred.
         4. Suggestion of 3-5 books/subjects the journalist should research to write this article.
        """
        generation_config = {
                            "max_output_tokens": 4048,
                            "temperature": 0.9,
                            "top_p": 0.4
                          }
  elif model_selection == "Gemini Pro Vision 1.0":
    # Pro 1.0 doesn't like many new line characters that exist in """blah blah""" format.
    prompt_generate = f"You are a journalist. Your job is to write an article with the provided video as your source. In the article, make sure to include:\n1. A summary of what happened in the video.\n2. Your interpretation of events.\n3. Analysis of why these events occurred.\n4. Suggestion of 3-5 books/subjects the journalist should research to write this article."
    generation_config = {
                        "max_output_tokens": 2048,
                        "temperature": 1,
                        "top_p": 0.4
                      }

  final_prompt_generate = st.text_area(label = "Prompt", value=prompt_generate, height=250)

  buttons_generate = []
  for i in range(TOP_N):
    buttons_generate.append(st.button(f"Generate Article from video: {neighbors[i]['result']}"))


  for i, button_generate in enumerate(buttons_generate):
    if button_generate:
      if model_selection == "Gemini Pro Vision 1.5":
        gcs_uri_generate = f"gs://geminipro-15-video-source-parts/{neighbors[i]['gcs_file']}"
      elif model_selection == "Gemini Pro Vision 1.0": # TODO: model only response with "good"
        gcs_uri_generate = f"gs://videosearch_video_source_parts/{neighbors[i]['gcs_file']}"

      print(gcs_uri_generate)
      input_file_generate = [
        Part.from_uri(uri = gcs_uri_generate, mime_type="video/mp4"),
        final_prompt_generate
        ]
      print(input_file_generate)
      response_generate = model_gem.generate_content(input_file_generate,
                                            generation_config=generation_config)
      print(response_generate)
      st.write(response_generate.text)
      st.write(f"{i+1} button was clicked")


# QA

st.header("Q&A with videos")
st.text("Ask questions against a video")



if "neighbor_result" in st.session_state:
  neighbors = st.session_state["neighbor_result"]
  file_name_list = [] # Put file names in list for streamlit radio object options
  name_to_uri_dict = {} # Map file name to uri to pass into model
  for i,neighbor in enumerate(neighbors):
    file_name = neighbor['file']
    file_name_list.append(file_name)
    name_to_uri_dict[file_name] = neighbor['gcs_file']

  video_selection_name = st.radio(label = "Select one video", options=file_name_list)

  question = st.text_input(label="Question")
  button_qa = st.button(label = "Ask")
  if question and button_qa:
    if model_selection == "Gemini Pro Vision 1.5":
      gcs_uri_qa = f"gs://geminipro-15-video-source-parts/{name_to_uri_dict[video_selection_name]}"
    elif model_selection == "Gemini Pro Vision 1.0":
      gcs_uri_qa = f"gs://videosearch_video_source_parts/{name_to_uri_dict[video_selection_name]}"

    prompt_qa = f"Your job is to anwswer the following question using the video provided. Question: {question}. If you do not know the answer of the question is unrelated to the video response with 'I don't know'."

    input_file_generate = [
      Part.from_uri(uri = gcs_uri_qa, mime_type="video/mp4"),
      prompt_qa
      ]
    response_generate = model_gem.generate_content(input_file_generate)
    st.write(response_generate.text)



import streamlit as st
from google.cloud import aiplatform_v1
from google.cloud import storage
import vertexai
import math
from vertexai.generative_models import GenerativeModel, Part
from vertexai.vision_models import MultiModalEmbeddingModel
import datetime
import requests
import base64
import google.auth.transport.requests

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

# Function to get signed GCS urls
def getSignedURL(filename, bucket, action):
  blob = bucket.blob(filename)
  url = blob.generate_signed_url(
    expiration=datetime.timedelta(minutes=60),
    method=action,
    version="v4"
  )
  return url


# Function to display videos in N columns
def columnize_videos(result_list, num_col = 2):
  cols = st.columns(num_col)
  try:
    for row in range(math.ceil(len(result_list) / num_col)):
      for col in range(num_col):
        item = row * num_col + col
        cols[col].text(result_list[item]["result"])
        cols[col].video(result_list[item]["signedURL"], start_time=result_list[item]["start_sec"])
        cols[col].text(f"Similarity score: {result_list[item]['distance']:.4f}")
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
    print(f"Getting Signed URL - Video Name: {video_name}")

    # Better than downloading to temp file in Cloud run b/c this makes a direct link to GCS (rather than having Cloud run be proxy)
    signedURL = getSignedURL(video_name,
                             storage_client.bucket("videosearch_video_source_parts"),
                             "GET")

    print(f"Received Signed URL: {signedURL}")

    d = {
      "result" : f"Result #{n+1}\nTimestamps:{start_sec}->{start_sec+5}\n{neighbors[n].datapoint.datapoint_id}", #5 because that's what I set IntervalSec in embeddings api call
      "gcs_file": f"{video_name}",
      "file": f"{neighbors[n].datapoint.datapoint_id}",
      "start_sec": start_sec,
      "distance": neighbors[n].distance,
      "signedURL": signedURL,
    }
    videos.append(d)
  return videos

# Function to upload bytes object to GCS bucket
def upload_video_file(uploaded_file, bucket_name):

  bucket = storage_client.bucket(bucket_name)

  url = getSignedURL(uploaded_file.name, bucket, "PUT")
  # blob.upload_from_string(uploaded_file.read())

  print(f"Upload Signed URL: {url}")

  encoded_content = base64.b64encode(uploaded_file.read()).decode("utf-8")

  # Again leverage signed URLs here to circumvence Cloud Run's 32 MB upload limit
  response = requests.put(url, encoded_content, headers={'Content-Type': 'video/mp4'})

  if response.status_code == 200:
    st.write("Upload Successful")
  else:
    st.write("Upload Unseccessful")

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
        This application is meant to be your go to destination for all
        your video needs. This has externally and internally facing applications.

        Here are some pre-loaded videos you can find in this database with example search queries you can try:
          - animals.mp4 (search for "tiger")
          - chicago.mp4 (search fro "taxi")
          - JaneGoodall.mp4 (search for "Jane Goodall")
          - googlework_short.mp4 (search for "cow")
          - hockey video (search for "ice")

        You are not required to upload a video for the features below but you can.

        Here are some things you can do:

          1. Similarity search through all videos in FakeCompany's database (start here)
          2. Summarize video
          3. Generate analytical article based on video
          4. Ask questions of video
          5. Upload a video file to database
        """)

st.header("Similarity search through all videos in FakeCompany's database")

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

  # TODO: delete temp files. or make work without temp files?

# Shot List

st.header("Generate shot list from video")
st.text("Click one of the buttons below to generate an shot list from the video.\nNOTE: Gemini Pro 1.0 does not work well for this task.")

if "neighbor_result" in st.session_state:
  neighbors = st.session_state["neighbor_result"] # need to store in session state because otherwises it's not accessible

  # Allow the user to modify the prompt
  if model_selection == "Gemini Pro Vision 1.5":
        prompt_shot_list = f"You are tasked with generating a shot list for the attached video. A shot is a series of frames that runs for an uninterrupted period of time.A shot list is a document that maps out everything that will happen in a scene of a video. It describes each shot within the videoFor each shot, make sure to include:- A description- A timestamp for the duration of the shot- Shot type (close-up, wide-shot, etc)- Camera angle- Location- summary of audio contentYou must include each of the element for each shot in the video. If you are uncertain about one of the elements say you are uncertain and explain why."
        generation_config = {
                            "max_output_tokens": 4048,
                            "temperature": 0.9,
                            "top_p": 0.4
                          }
  elif model_selection == "Gemini Pro Vision 1.0":
    # Pro 1.0 doesn't like many new line characters that exist in """blah blah""" format.
    prompt_shot_list = f"""
        You are tasked with generating a shot list for the attached video. A shot is a series of frames that runs for an uninterrupted period of time.
        A shot list is a document that maps out everything that will happen in a scene of a video. It describes each shot within the video
        For each shot, make sure to include:
        - A description
        - A timestamp for the duration of the shot
        - Shot type (close-up, wide-shot, etc)
        - Camera angle
        - Location
        You must include each of the element for each shot in the video. If you are uncertain about one of the elements say you are uncertain and explain why.
        """
    generation_config = {
                        "max_output_tokens": 2048,
                        "temperature": 1,
                        "top_p": 0.4
                      }

  final_prompt_shot_list = st.text_area(label = "Prompt", value=prompt_shot_list, height=250)

  buttons_shot_list = []
  for i in range(TOP_N):
    buttons_shot_list.append(st.button(f"Generate shot list from video: {neighbors[i]['result']}"))


  for i, button_shot_list in enumerate(buttons_shot_list):
    if button_shot_list:
      if model_selection == "Gemini Pro Vision 1.5":
        gcs_uri_shot_list = f"gs://geminipro-15-video-source-parts/{neighbors[i]['gcs_file']}"
      elif model_selection == "Gemini Pro Vision 1.0": # TODO: model only response with "good"
        gcs_uri_shot_list = f"gs://videosearch_video_source_parts/{neighbors[i]['gcs_file']}"

      print(gcs_uri_shot_list)
      input_file_shot_list = [
        Part.from_uri(uri = gcs_uri_shot_list, mime_type="video/mp4"),
        final_prompt_shot_list
        ]
      print(input_file_shot_list)
      response_generate = model_gem.generate_content(input_file_shot_list,
                                            generation_config=generation_config)
      print(response_generate)
      st.write(response_generate.text)
      st.write(f"{i+1} button was clicked")

# Summarize

st.header("Summarize video")
st.text("Click one of the buttons below to summarize the video. This will summarize the entire video.\nPro 1.5 will take timestamps into account and will only summarize the timestamp specified.\nPro 1.0 will not. Prompt is not editable.")

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

      st.text_area(label = "Prompt", value = prompt_summarize, height = 250)
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
st.text("Click one of the buttons below to generate an article from the video.\nPrompt is editable.")

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
    buttons_generate.append(st.button(f"Generate article from video: {neighbors[i]['result']}"))

  for i, button_generate in enumerate(buttons_generate):
    if button_generate:
      if model_selection == "Gemini Pro Vision 1.5":
        gcs_uri_generate = f"gs://geminipro-15-video-source-parts/{neighbors[i]['gcs_file']}"
      elif model_selection == "Gemini Pro Vision 1.0": # TODO: model only response good"
        gcs_uri_generate = f"gs://videosearch_video_source_parts/{neighbors[i]['gcs_file']}"
      print(gcs_uri_generate)
      input_file_generate = [
        Part.from_uri(uri = gcs_uri_generate, mime_type="video/mp4"),
        final_prompt_generate]
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

# this doesn't work on Cloud run
st.header("Upload Video File")
st.text("Upload a video file from your local machine to the video database")

uploaded_file = st.file_uploader("Choose a video...", type=["mp4"])
upload_file_start = st.button("Upload File")

if upload_file_start:
    upload_video_file(uploaded_file=uploaded_file, bucket_name="videosearch_source_videos")

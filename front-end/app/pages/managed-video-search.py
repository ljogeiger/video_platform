import streamlit as st
from google.cloud import aiplatform_v1
from google.cloud import storage
import vertexai
import math
import utils
from vertexai.generative_models import GenerativeModel, Part
from vertexai.vision_models import MultiModalEmbeddingModel
import datetime
import requests
import google.auth.transport.requests
from google.auth import impersonated_credentials
from visionai.python.gapic.visionai import visionai_v1
from visionai.python.net import channel
from visionai.python.warehouse.transformer import \
    asset_indexing_transformer as ait
from visionai.python.warehouse.utils import (vod_asset, vod_corpus,
                                             vod_index_endpoint)
from st_pages import Page, show_pages, add_page_title

# Set Variables
PROJECT_ID = "vision-warehouse-demo-421419"
PROJECT_NUMBER = "191387109286"
REGION = "us-central1"
ENV = "PROD"
INDEX_DISPLAY_NAME = "Demo Index"
INDEX_ENDPOINT_DISPLAY_NAME = "Demo Index Endpoint"
CORPUS_DISPLAY_NAME = "Demo corpus"
CORPUS_ID = "1678845387635490856"
INDEX_ENDPOINT_ID = "ie-4504795562690827196"
DEPLOYED_INDEX_ID = "index-2722830910301969802"

# Warehouse Client setup
warehouse_endpoint = channel.get_warehouse_service_endpoint(channel.Environment[ENV])
warehouse_client = visionai_v1.WarehouseClient(
    client_options={"api_endpoint": warehouse_endpoint}
)

corpus_name = visionai_v1.WarehouseClient.corpus_path(
        PROJECT_NUMBER, REGION, CORPUS_ID
    )


index_name = "{}/indexes/{}".format(corpus_name, DEPLOYED_INDEX_ID)
print(index_name)
index = warehouse_client.get_index(visionai_v1.GetIndexRequest(name=index_name))
index_endpoint_name = index.deployed_indexes[0].index_endpoint

show_pages(
  [
    Page("app/home.py", "Home"),
    Page("app/pages/custom-video-search.py","Custom Video Search"),
    Page("app/pages/managed-video-search.py","Managed Video Search"),
  ]
)

# Get search query from the user
search_query = st.text_input("Search Managed Video Search (ex: tiger walking)")
search_button = st.button(label="Search")

if search_button and search_query:

  # Execute search across batch video warehouse
  search_response = warehouse_client.search_index_endpoint(
      visionai_v1.SearchIndexEndpointRequest(
          index_endpoint=index_endpoint_name,
          text_query=search_query,
          page_size=10, # adjust this for more or less results
      )
  )
  print(search_response)

  # Parse the response
  result_list = []
  count = 1
  for page in search_response.pages:
    for item in page.search_result_items:
      # Get asset name, URI, start_time, end_time
      # Similarity score is coming but not available yet
      asset_name = item.asset
      asset_start_time = item.segment.start_time
      asset_end_time = item.segment.end_time
      print(asset_name)
      request = visionai_v1.GenerateRetrievalUrlRequest(name = asset_name)
      asset_uri = warehouse_client.generate_retrieval_url(request)
      print(asset_uri)
      video_name = asset_uri.signed_uri.split("https://storage.googleapis.com/")[1].split("?")[0].replace("%2F", "/")
      asset_start_time_formatted = int(asset_start_time.timestamp())
      asset_end_time_formatted = int(asset_end_time.timestamp())
      result_list.append(
        {
          "result": f"""Result #{count}\nTimestamps:{asset_start_time_formatted}->{asset_end_time_formatted}\n{video_name}""",
          "signedURL": asset_uri.signed_uri,
          "start_sec": asset_start_time_formatted,
          "end_time": asset_end_time_formatted,
          "distance": None
        }
      )
      count+=1

  utils.columnize_videos(st, result_list, 2)


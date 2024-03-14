from cloudevents.http import CloudEvent
from google.cloud import storage
from google.cloud import aiplatform
from google.protobuf import struct_pb2
from moviepy.editor import *
from google.cloud.storage import transfer_manager

import os
import tempfile
import base64
import functions_framework
import subprocess
import requests
import json
import google.auth.transport.requests
import math

storage_client = storage.Client()

# change these
PROJECT_NAME="videosearch-cloudspace"
REGION="us-central1"
INDEX_ID="7673540028760326144"

def getToken():
    creds, project = google.auth.default()
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    return creds.token

def upsertDataPoint(datapoint_id, datapoint_content):

    type_datapointcontent = type(datapoint_content)
    type_datapointid = type(datapoint_id)

    print(f"datapoint id: {datapoint_id}, type: {type_datapointid}")
    print(f"datapoint content: {datapoint_content[0]}, type: {type_datapointcontent}")

    token = getToken()

    response = requests.post(f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_NAME}/locations/{REGION}/indexes/{INDEX_ID}:upsertDatapoints",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        json = {
            "datapoints": [
                {
                    "datapointId": datapoint_id,
                    "featureVector": datapoint_content
                }
            ]
        })

    print(response.json())

    if response.status_code == 200:
        return "success"
    else:
        return "error"

def split_video_by_duration(
        video,
        seconds_per_part = 120,
        output_filepath_template = "/tmp/part-%d.mp4"):

     # Calculate the duration of the video in seconds
    duration = int(video.duration)

    # print(f"Video Length: {duration}")

    # Calculate the number of parts the video will be split into
    parts = math.ceil(duration / seconds_per_part)

    # Split and export the video
    output_filepaths = []
    for part in range(parts):
        # Calculate start and end times for the current part
        start_time = part * 60
        end_time = (part + 1) * 60

        # Ensure end time does not exceed video duration
        end_time = min(end_time, duration)

        # Clip the video for the current part
        current_part = video.subclip(start_time, end_time)

        # Export the current part
        output_filepath = output_filepath_template % part
        current_part.write_videofile(
            output_filepath,
            audio = False # set this to True if you have audio files
            )
        output_filepaths.append(output_filepath)

    return output_filepaths

# Triggered by a change in a storage bucket
@functions_framework.cloud_event
def main(cloud_event: CloudEvent):
    """This function is triggered by a change in a storage bucket.

    Args:
        cloud_event: The CloudEvent that triggered this function.
    Returns:
        embedding file + complete if successful
        embedding file + unsuccessful if error
    """
    destination_file = "/tmp/video.mp4"

    request = cloud_event.data
    print(request)

    input_bucket_name = request["bucket"]
    parts_bucket_name = "videosearch_video_source_parts"
    output_bucket_name = "videosearch_embeddings"
    input_video_name = request["name"]
    stripped_input_video_name = input_video_name.replace(".mp4","")

    with open(f'{destination_file}','wb') as file_obj:
        storage_client.download_blob_to_file(f'gs://{input_bucket_name}/{input_video_name}',file_obj)

    vid = VideoFileClip(destination_file)
    if vid: print("Vid Successful")
    else: print("Vid Unsuccessful")

    # could upload directly in this function to save space.
    # Tradeoff is I might encounter function timeout because all files would be uploaded individually
    # TODO: make more efficient for videos shorter than 120 seconds
    split_video_paths = split_video_by_duration(vid)

    results = transfer_manager.upload_many_from_filenames(
        bucket=storage_client.bucket(parts_bucket_name),
        filenames=split_video_paths,
        source_directory="",
        blob_name_prefix=stripped_input_video_name
    )

    for name, result in zip(split_video_paths, results):
        # The results list is either `None` or an exception for each filename in
        # the input list, in order.

        if isinstance(result, Exception):
            print("Failed to upload {} due to exception: {}".format(name, result))
        else:
            print("Uploaded {} to {}.".format(name, parts_bucket_name))

    token = getToken()

    # get embeddings
    for part in split_video_paths:
      name = f"{stripped_input_video_name}{part}"
      print(f"Generating embeddings for part: gs://{name}")

      response = requests.post(f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_NAME}/locations/{REGION}/publishers/google/models/multimodalembedding@001:predict",
          headers = {
              "Authorization": f"Bearer {token}"
          },
          json = {
              "instances": [
                  {"video": {
                      "gcsUri": f"gs://{parts_bucket_name}/{name}",
                      "videoSegmentConfig": {
                          "intervalSec": 5
                        }
                      }
                  }
              ]
          })

      print(response.json())


      embeddings_list = response.json()["predictions"][0]['videoEmbeddings']

      # TODO: embeddings should be stored by timestamps
      count = 0
      for embedding_object in embeddings_list:
        count+=1
        embedding = embedding_object['embedding']
        id = f"{name}_{count}"

        json_object = {
            "id": f"{id}",
            "embedding": embedding
        }

        # NOTE: doesn't not check for repeated uploads of same image. Would need to include some logic in order to avoid overwriting already uploaded images
        # Vector Search does check for duplicates before upserting so it wouldn't affect the index performance wise. Although you would likely get charged for the bytes transfered.

        output_bucket = storage_client.bucket(output_bucket_name)

        new_blob = output_bucket.blob(f"{id}.json")
        new_blob.upload_from_string(
            data=json.dumps(json_object),
            content_type='application/json'
        )

        upsert_result = upsertDataPoint(id, embedding)
        print(f"Upsert Result: {upsert_result}")

        if upsert_result == "success":
            print(f"{id}.json complete")
        else:
            print(f"{id}.json unsuccessful")

    return

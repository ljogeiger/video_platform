import google.auth.transport.requests
from google.auth import impersonated_credentials
import datetime
import math

def getCreds():
  creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
  auth_req = google.auth.transport.requests.Request()
  creds.refresh(auth_req)
  return creds

#token for removing datapoints from vector search
def getToken():
  creds, _ = google.auth.default()
  auth_req = google.auth.transport.requests.Request()
  creds.refresh(auth_req)
  return creds.token

# Function to get signed GCS urls
def getSignedURL(filename, bucket, action):

  # creds = service_account.Credentials.from_service_account_file('./credentials.json')
  creds = getCreds()

  signing_credentials = impersonated_credentials.Credentials(
    source_credentials= creds,
    target_principal='videosearch-streamlit-frontend@videosearch-cloudspace.iam.gserviceaccount.com',
    target_scopes='',
    lifetime=500
  )

  blob = bucket.blob(filename)

  url = blob.generate_signed_url(
    expiration=datetime.timedelta(minutes=60),
    method=action,
    credentials=signing_credentials,
    version="v4"
  )
  return url


# Function to display videos in N columns
def columnize_videos(st, result_list, num_col = 2):
  cols = st.columns(num_col)
  try:
    for row in range(math.ceil(len(result_list) / num_col)):
      for col in range(num_col):
        item = row * num_col + col
        cols[col].text(result_list[item]["result"])
        cols[col].video(result_list[item]["signedURL"], start_time=result_list[item]["start_sec"])
        if result_list[item]['distance'] != None:
          cols[col].text(f"Similarity score: {result_list[item]['distance']:.4f}")
  except IndexError as e:
     print(f"Index out of bounds: {e}")
  return



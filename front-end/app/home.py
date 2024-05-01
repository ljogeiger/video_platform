import streamlit as st
from st_pages import Page, show_pages, add_page_title

show_pages(
  [
    Page("home.py", "Home"),
    Page("pages/custom-video-search.py","Custom Video Search"),
    Page("pages/managed-video-search.py","Managed Video Search"),
  ]
)

st.title("Cymbal AI - Video Platform")

st.text("""
        Welcome to Cymbal AI's Video Platform!
        This application is meant to be your go to destination for all
        your video needs. This has externally and internally facing applications.

        Here are some pre-loaded videos you can find in this database with example search queries you can try:
          - animals.mp4 (search for "tiger walking")
          - chicago.mp4 (search fro "taxi in chicago")
          - JaneGoodall.mp4
          - googlework_short.mp4

        """)
st.header("Custom Video Search")
st.text("""
        Custom Video Search generates 5 second interval embeddings using Google's
        multimodal embeddings API and stores them in Vector Search. This generates embeddings
        on the video frames. The semantic search does not support audio (but it is possible
        using speech-to-text model and embedding the text). Gemini 1.5 API does support audio.

        Here are some things you can do on this page:
          1. Similarity search through all videos in Cymbal AI's database (start here)
          2. Summarize video
          3. Generate analytical article based on video
          4. Ask questions of video
          5. Upload a video file to database

        Below you will find an architecture diagram:
        """)
st.image('video_platform_architecture.png')

st.header("Managed Video Search")
st.text("""
        Managed Video Search is powered by GCP's Vision Warehouse product.
        The product generates and manages embeddings for you so you can focus on building your
        application.

        Currently this doesn't support audio, but it is coming soon.

        The architecture is pictured below:

        """)
st.image('Managed_Video_Search.png')



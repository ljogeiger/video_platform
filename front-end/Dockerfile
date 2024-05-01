FROM python:3.11
RUN mkdir .streamlit
COPY .streamlit/config.toml .streamlit/config.toml

COPY . .
RUN pip install -r requirements.txti
RUN pip install visionai-0.0.6-py3-none-any.whl
RUN make ./app

EXPOSE 8080

CMD ["streamlit", "run", "app/Instructions.py", "--server.port=8080", "server.address=0.0.0.0"]

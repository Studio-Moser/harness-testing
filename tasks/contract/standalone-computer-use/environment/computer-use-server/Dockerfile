FROM mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d

RUN python -m pip install --no-cache-dir mcp==2.1.1 playwright==1.62.0

COPY Server.py /opt/computer-use/Server.py
RUN mkdir -p /var/log/computer-use

CMD ["python", "/opt/computer-use/Server.py"]

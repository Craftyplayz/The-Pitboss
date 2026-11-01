FROM python:3.12-slim

WORKDIR /app
# discord.py decodes the voice audio it records with libopus
RUN apt-get update && apt-get install -y --no-install-recommends libopus0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py CHANGELOG.md ./
COPY cogs/ cogs/
COPY core/ core/
COPY mockups/ mockups/
COPY pages/ pages/
COPY static/ static/
COPY assets/ assets/

# unbuffered so logs show up in `docker logs` immediately
CMD ["python", "-u", "bot.py"]

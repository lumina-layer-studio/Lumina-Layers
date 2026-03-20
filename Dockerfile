# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for pycairo and opencv
# libcairo2-dev, pkg-config -> for pycairo
# libgl1, libglib2.0-0 -> for opencv-python
RUN apt-get update && apt-get install -y \
    gcc \
    pkg-config \
    libcairo2-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt /app/

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . /app/

# Expose the port Gradio runs on
EXPOSE 7860

# Define environment variable to ensure output is flushed
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "main.py"]

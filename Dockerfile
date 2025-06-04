# Use a minimal Python base image
FROM python:3.13-alpine

# Set working directory
WORKDIR /app

# Copy all files into the container
COPY . .

# Create output directory (optional, script does this too)
RUN mkdir -p /app/test_xmls

# Accept NUM_FILES as env or CMD arg
ENV NUM_FILES=5

# Run script on container start
CMD ["python", "generator.py"]

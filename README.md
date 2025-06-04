# deps

## PDF & XML Generator for JMeter Load Testing

This project provides a Dockerized solution to generate PDF files and corresponding XML metadata files. It's especially useful for performance and load testing scenarios, such as those driven by Apache JMeter.

## 📦 Features

- Creates multiple PDF files of varying sizes.
- Encodes each PDF file in Base64 format.
- Embeds Base64-encoded content inside XML under a `<content>` tag.
- Generates a `jmeter_data.csv` file suitable for use in JMeter.
- Fully containerized for easy setup and portability.

---

## 🛠️ Build the Docker Image

To build the Docker image:

```bash
docker build -t pdf-xml-gen .

🚀 Run the Container
To generate PDFs, XML files, and the JMeter-compatible CSV file:

Via CLI Argument

docker run --rm \
  -v "$PWD/output:/app/test_xmls" \
  -v "$PWD/jmeter_data.csv:/app/jmeter_data.csv" \
  pdf-xml-gen --num 100

Via ENV

docker run --rm \
  -v "$PWD/output:/app/test_xmls" \
  -v "$PWD/jmeter_data.csv:/app/jmeter_data.csv" \
  -e NUM_FILES=100 \
  pdf-xml-gen

🔁 Volume Mounts
-v "$PWD/output:/app/test_xmls"
Mounts the local output/ folder so you can access the generated XML files outside the container.

-v "$PWD/jmeter_data.csv:/app/jmeter_data.csv"
Maps the root project directory to retrieve the generated CSV file.

📂 Output
XML files will be saved in the output/ directory.

A JMeter-compatible jmeter_data.csv file will appear in the project root.

🧪 Use with JMeter
You can plug the jmeter_data.csv file into your JMeter test plan using a CSV Data Set Config element to simulate real file uploads and metadata handling during performance testing.

✅ Prerequisites
Docker installed and running.

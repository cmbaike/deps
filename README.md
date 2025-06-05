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

| Flag           | Behavior                                                       |
| -------------- | ---------------------------------------------------------------|
|`--num 100`     | Genarates 100 xml with varying attachment size not greater 10Mb|
| `--upload-s3`  | Uploads XML and CSV to the S3 bucket                           |
| `--cleanup`    | Deletes local files after upload                               |
| `--cleanup-s3` | Deletes uploaded files from S3 after upload                    |


Via CLI Argument

Generate Files Locally Only
```bash docker run --rm \
          -v "$PWD:/app" \
          pdf-xml-gen \
          --num 100

🔁 Volume Mounts
-v "$PWD/output:/app/test_xmls"
Mounts the local output/ folder so you can access the generated XML files outside the container.

-v "$PWD/jmeter_data.csv:/app/jmeter_data.csv"
Maps the root project directory to retrieve the generated CSV file.

📂 Output
XML files will be saved in the output/ directory.

A JMeter-compatible jmeter_data.csv file will appear in the project root.

Generate Files and Upload to S3

```bash docker run --rm \
     -e AWS_ACCESS_KEY_ID=your_key \
     -e AWS_SECRET_ACCESS_KEY=your_secret \
     -e AWS_DEFAULT_REGION=your_region \
     -v "$PWD:/app" \
     pdf-xml-gen \
     --num 100 \
     --upload-s3 \
     --s3-bucket your-bucket-name


-v "$PWD/jmeter_data.csv:/app/jmeter_data.csv"
Maps the root project directory to retrieve the generated CSV file.

Cleanup Local Files Only
```bash docker run --rm \
          -v "$PWD:/app" \
          pdf-xml-gen \
          --cleanup


Cleanup S3 Files Based on CSV
```bash docker run --rm \
          -e AWS_ACCESS_KEY_ID=... \
          -e AWS_SECRET_ACCESS_KEY=... \
          -e AWS_DEFAULT_REGION=... \
          -v $PWD:/app \
          pdf-xml-gen \
          --cleanup-s3 --s3-bucket your-bucket-name

🧪 Use with JMeter
You can plug the jmeter_data.csv file into your JMeter test plan using a CSV Data Set Config element to simulate real file uploads and metadata handling during performance testing.

✅ Prerequisites
Docker installed and running.

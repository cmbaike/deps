
import os
import base64
import uuid
import random
import csv
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from botocore.exceptions import ClientError
import argparse
import boto3
import shutil
from functools import partial
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import io
from reportlab.lib.utils import ImageReader
import numpy as np
from PIL import Image
from PyPDF2 import PdfWriter, PdfReader
import copy

# =========================
# Constants & global config
# =========================
OUTPUT_DIR = "/test_xmls/"
CSV_FILE = "jmeter_data.csv"
NUM_FILES = 5

# Absolute caps
MAX_PER_ATTACHMENT_MB = 2.0        # each attachment ≤ 2 MB
MAX_TOTAL_ATTACHMENTS_MB = 10.0    # sum of attachments ≤ 10 MB
PDF_SAFETY_BYTES = 4096            # 4 KB safety margin under caps

# Image generation settings (compact & predictable)
IMG_WIDTH = 800
IMG_HEIGHT = 800
JPEG_QUALITY = 60  # balanced size/quality


# ================
# S3 Helper funcs
# ================
def download_csv_from_s3(bucket_name, s3_key, local_file_path):
    s3 = boto3.client('s3')
    try:
        s3.download_file(bucket_name, s3_key, local_file_path)
        print(f"Downloaded CSV from s3://{bucket_name}/{s3_key} to {local_file_path}")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchKey':
            print(f"Error: The CSV file s3://{bucket_name}/{s3_key} does not exist.")
        else:
            print(f"Error: Failed to download CSV from s3://{bucket_name}/{s3_key}. {e}")


def delete_csv_from_s3(bucket_name, csv_key):
    s3 = boto3.client('s3')
    try:
        s3.delete_object(Bucket=bucket_name, Key=csv_key)
        print(f"Deleted CSV from s3://{bucket_name}/{csv_key}")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchKey':
            print(f"Error: The CSV file s3://{bucket_name}/{csv_key} does not exist.")
        else:
            print(f"Error: Failed to delete CSV file s3://{bucket_name}/{csv_key}. {e}")


def upload_to_s3(file_path, bucket_name, s3_key):
    s3 = boto3.client('s3')
    s3.upload_file(file_path, bucket_name, s3_key)
    print(f"Uploaded {file_path} to s3://{bucket_name}/{s3_key}")


def upload_to_s3_from_memory(buffer, bucket_name, key):
    s3 = boto3.client('s3')
    s3.upload_fileobj(buffer, bucket_name, key)
    print(f"Uploaded to s3://{bucket_name}/{key}")


def cleanup_s3_from_csv(bucket_name, csv_path):
    s3 = boto3.client('s3')
    objects_to_delete = []

    if not os.path.exists(csv_path):
        print(f"CSV file not found locally: {csv_path}")
        return

    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = f"test_xmls/{row['filename']}"
            objects_to_delete.append({'Key': key})

    if objects_to_delete:
        s3.delete_objects(Bucket=bucket_name, Delete={'Objects': objects_to_delete})
        print(f"Deleted {len(objects_to_delete)} objects from s3://{bucket_name}")
    else:
        print("No objects found to delete.")


# =================
# PDF/Image helpers
# =================
def _bytes_from_mb(mb: float) -> int:
    return int(mb * 1024 * 1024)


def _clamp(value, lo, hi):
    return max(lo, min(value, hi))


def _effective_caps(per_cap_mb: float, total_mb: float):
    """
    Enforce the global caps (2 MB per attachment, 10 MB total).
    """
    per_cap_mb = _clamp(per_cap_mb, 0.001, MAX_PER_ATTACHMENT_MB)
    total_mb = _clamp(total_mb, 0.001, MAX_TOTAL_ATTACHMENTS_MB)
    return per_cap_mb, total_mb


def _plan_attachments(total_mb: float, per_cap_mb: float):
    """
    Split total into chunks not exceeding per_cap_mb.
    E.g., total=8, per_cap=2 => [2,2,2,2]
          total=5, per_cap=2 => [2,2,1]
    """
    per_cap_mb, total_mb = _effective_caps(per_cap_mb, total_mb)

    sizes = []
    remaining = total_mb
    while remaining > 1e-6:
        chunk = min(per_cap_mb, remaining)
        sizes.append(round(chunk, 3))
        remaining = round(remaining - chunk, 6)

    # Ensure rounding never exceeds total
    if sum(sizes) - total_mb > 1e-6:
        delta = sum(sizes) - total_mb
        sizes[-1] = max(0.001, round(sizes[-1] - delta, 3))

    return sizes


def _target_bytes_with_safety(mb: float) -> int:
    """
    Convert MB to bytes and subtract a small safety margin so we never overshoot.
    """
    return max(1, _bytes_from_mb(mb) - PDF_SAFETY_BYTES)


def generate_large_image(width=IMG_WIDTH, height=IMG_HEIGHT, quality=JPEG_QUALITY):
    """
    Generate a random RGB image and return it as a JPEG BytesIO object.
    """
    array = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
    img = Image.fromarray(array, 'RGB')
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    buffer.seek(0)
    return buffer


def generate_pdf_of_size(size_mb: float) -> io.BytesIO:
    """
    Generate a PDF as close as possible to the target size WITHOUT overshooting.
    """
    target_size_bytes = _target_bytes_with_safety(size_mb)

    pages = []
    while True:
        # Build a 1-page PDF with an image
        img_buf = generate_large_image()
        single_page_pdf = io.BytesIO()
        c = canvas.Canvas(single_page_pdf, pagesize=letter)
        img = ImageReader(img_buf)
        c.drawImage(img, 50, 50, width=500, height=500, preserveAspectRatio=True, anchor='c')
        c.showPage()
        c.save()
        single_page_pdf.seek(0)

        # Tentatively add to a temp writer to see resulting size
        temp_writer = PdfWriter()
        for p in pages:
            temp_writer.add_page(p)
        reader = PdfReader(single_page_pdf)
        temp_writer.add_page(reader.pages[0])

        temp_buffer = io.BytesIO()
        temp_writer.write(temp_buffer)
        temp_size = temp_buffer.getbuffer().nbytes

        if temp_size > target_size_bytes:
            break
        pages.append(reader.pages[0])
        if temp_size == target_size_bytes:
            break

    # Finalize PDF
    if not pages:
        # Minimal fallback (if even one page would exceed target safety)
        minimal_buf = io.BytesIO()
        c = canvas.Canvas(minimal_buf, pagesize=letter)
        c.drawString(72, 720, "Auto-generated placeholder page")
        c.showPage()
        c.save()
        minimal_buf.seek(0)
        pdf_data = minimal_buf.getvalue()
    else:
        final_writer = PdfWriter()
        for p in pages:
            final_writer.add_page(p)
        final_buffer = io.BytesIO()
        final_writer.write(final_buffer)
        pdf_data = final_buffer.getvalue()

    # Pad upward if needed (but never over target)
    if len(pdf_data) < target_size_bytes:
        pad_len = target_size_bytes - len(pdf_data)
        overhead = len(b"\n%PADDING\n")
        payload = max(pad_len - overhead, 0)
        pdf_data += b"\n%PADDING\n" + (b"0" * payload)

    result = io.BytesIO(pdf_data)
    print(f"PDF generated: {len(pdf_data)/1024:.2f} KB (target ≤ {target_size_bytes/1024:.2f} KB)")
    return result


# ========================
# XML helpers (attachments)
# ========================
def _find_parent(root: ET.Element, target: ET.Element):
    """
    Find parent of a given element (ElementTree has no .getparent()).
    """
    for parent in root.iter():
        for child in list(parent):
            if child is target:
                return parent
    return None


def _is_attachment_like(elem: ET.Element, ns: dict) -> bool:
    return (elem.find("./ns:content", ns) is not None and
            elem.find("./ns:filename", ns) is not None)


def _find_attachment_node_template(root: ET.Element, ns: dict):
    """
    Heuristic: the 'attachment node' is any element that contains BOTH
    <ns:content> and <ns:filename> children. We'll clone this.
    """
    for elem in root.iter():
        if _is_attachment_like(elem, ns):
            return elem
    return None


def _find_all_attachment_nodes(root: ET.Element, ns: dict):
    nodes = []
    for elem in root.iter():
        if _is_attachment_like(elem, ns):
            nodes.append(elem)
    return nodes


def _set_child_text(elem: ET.Element, xpath: str, ns: dict, text: str):
    child = elem.find(xpath, ns)
    if child is not None:
        child.text = text


def remove_all_attachments(root: ET.Element, ns: dict):
    """
    Remove all nodes that look like attachments (have <filename> and <content>).
    """
    nodes = _find_all_attachment_nodes(root, ns)
    for node in nodes:
        parent = _find_parent(root, node)
        if parent is not None:
            parent.remove(node)


def inject_attachments_multiple(root: ET.Element, ns: dict, filenames_and_b64):
    """
    Replace existing attachment node(s) with one node per (filename, b64) pair.
    Each node includes <mimetype>application/pdf</mimetype>, <filename>, <content>.
    If filenames_and_b64 is empty, all existing attachments are removed.
    """
    # If no attachments requested, just remove and exit
    if not filenames_and_b64:
        remove_all_attachments(root, ns)
        return

    template = _find_attachment_node_template(root, ns)
    if template is None:
        raise RuntimeError("Could not locate an attachment node with <filename> and <content> to clone.")

    container = _find_parent(root, template)
    if container is None:
        raise RuntimeError("Could not determine container element for attachments.")

    # Remove existing <Attachments>-alike nodes (same tag as template)
    template_tag = template.tag
    for child in list(container):
        if child.tag == template_tag and _is_attachment_like(child, ns):
            container.remove(child)

    # Add one <Attachments> per file
    for idx, (fname, b64) in enumerate(filenames_and_b64, start=1):
        clone = copy.deepcopy(template)
        # Ensure required children exist; create them if missing
        if clone.find("./ns:mimetype", ns) is None:
            ET.SubElement(clone, f"{{{ns['ns']}}}mimetype")
        if clone.find("./ns:filename", ns) is None:
            ET.SubElement(clone, f"{{{ns['ns']}}}filename")
        if clone.find("./ns:content", ns) is None:
            ET.SubElement(clone, f"{{{ns['ns']}}}content")

        _set_child_text(clone, "./ns:mimetype", ns, "application/pdf")
        _set_child_text(clone, "./ns:filename", ns, fname)
        _set_child_text(clone, "./ns:content", ns, b64)

        # Optional: set sequence/index if schema has one
        for cand in ("./ns:sequenceNumber", "./ns:sequenceNo", "./ns:id", "./ns:documentSequenceId"):
            node = clone.find(cand, ns)
            if node is not None:
                node.text = str(idx)

        container.append(clone)


# ===========================
# Generation & Orchestration
# ===========================
def _infer_namespace_from_tree(tree: ET.ElementTree) -> dict:
    """
    Infer the default namespace from the root tag like '{uri}RootName'.
    Returns dict suitable for ElementTree finds: {'ns': uri}
    """
    root = tree.getroot()
    if root.tag.startswith('{'):
        uri = root.tag.split('}')[0][1:]
        ET.register_namespace('', uri)
        return {'ns': uri}
    # Fallback to known namespace if not namespaced
    uri = 'urn:wco:datamodel:WCO:CIS:1'
    ET.register_namespace('', uri)
    return {'ns': uri}


def save_xml_locally(xml_buffer, xml_filename):
    xml_path = os.path.join(OUTPUT_DIR, xml_filename)
    with open(xml_path, "wb") as f:
        f.write(xml_buffer.getvalue())
    print(f"Saved XML to {xml_path}")


def generate_and_update(
    i,
    base_xml: str,
    alt_base_xml: str | None,
    alt_base_percent: int,
    save_pdf=False,
    goods_percent=0,
    attachments_total_mb=2.0,
    attachment_max_mb=2.0,
    no_attachments_percent=0
):
    """
    Generate XML possibly with NO attachments (based on percentage) or with
    MULTIPLE attachments (total ≤ 10 MB, each ≤ 2 MB), using either the default
    base XML or an alternate base XML based on the given percentage.

    Returns:
      (xml_filename, xml_buffer, message_id, lrn, timestamp,
       has_attachments, attachment_count, attachments_total_mb_used, base_xml_used)
    """
    # Decide which base XML to use for this record
    use_alt = False
    if alt_base_xml and alt_base_percent > 0:
        use_alt = (random.random() < (float(alt_base_percent) / 100.0))
    base_xml_used = alt_base_xml if use_alt else base_xml

    # Decide if this record should have no attachments
    no_attach = random.random() < (float(no_attachments_percent) / 100.0)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    compact = now.strftime("%Y%m%d%H%M%S")

    filenames_and_b64 = []
    has_attachments = not no_attach
    attachment_count = 0
    total_mb_used = 0.0

    if not no_attach:
        # Determine the plan for attachments
        per_cap_mb, total_mb = _effective_caps(attachment_max_mb, attachments_total_mb)
        sizes_mb = _plan_attachments(total_mb, per_cap_mb)
        total_mb_used = float(round(sum(sizes_mb), 3))

        # Build PDFs and collect (filename, base64) pairs
        for idx, sz in enumerate(sizes_mb, start=1):
            pdf_filename = f"IE3FXX_{sz:.1f}MB_{compact}_{i}_{idx}.pdf"
            pdf_buffer = generate_pdf_of_size(sz)

            if save_pdf:
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
                with open(pdf_path, "wb") as f:
                    f.write(pdf_buffer.getvalue())
                print(f"Saved PDF to {pdf_path}")

            b64 = base64.b64encode(pdf_buffer.getvalue()).decode("utf-8")
            filenames_and_b64.append((pdf_filename, b64))

        attachment_count = len(filenames_and_b64)

    # Load chosen base XML and infer namespace
    tree = ET.parse(base_xml_used)
    ns = _infer_namespace_from_tree(tree)
    root = tree.getroot()

    GOODS_DESCRIPTIONS = ["FLOWERS", "chocolate", "cheese", "Make-up", "pasta", "Lemonade"]
    use_custom_goods = random.random() < (goods_percent / 100)
    goods_desc = random.choice(GOODS_DESCRIPTIONS) if use_custom_goods else "AERONAUTICAL INFO"

    # Generate IDs
    message_id = f"TEST-MSG-ID{uuid.uuid4()}"
    lrn = f"{compact}_001LRN"

    def set_text(tag_path, text):
        tag = root.find(tag_path, ns)
        if tag is not None:
            tag.text = text

    set_text(".//ns:descriptionOfGoods", goods_desc)
    set_text(".//ns:MessageId", message_id)
    set_text(".//ns:LRN", lrn)
    set_text(".//ns:Timestamp", timestamp)
    set_text(".//ns:documentIssueDate/ns:DateTime", timestamp)

    # Inject attachments or remove them all
    inject_attachments_multiple(root, ns, filenames_and_b64)

    # Decide filename AFTER we know whether we attached files
    suffix = "no_attachments" if not has_attachments else f"{total_mb_used:.1f}MB_total"
    # Include a hint of which base was used in the filename for easy auditing
    base_hint = os.path.splitext(os.path.basename(base_xml_used))[0]
    xml_filename = f"{base_hint}_updated_{suffix}_{compact}_{i}.xml"

    # Write XML to memory
    xml_buffer = io.BytesIO()
    tree.write(xml_buffer, encoding="utf-8", xml_declaration=True)
    xml_buffer.seek(0)

    # Return data for CSV
    return (
        xml_filename, xml_buffer,
        message_id, lrn, timestamp,
        has_attachments, attachment_count, total_mb_used, base_xml_used
    )


def main():
    parser = argparse.ArgumentParser(description="Generate XML with multiple ≤2MB attachments; optionally upload to S3")
    parser.add_argument("--num", type=int, default=5, help="Number of XML files to generate")
    parser.add_argument("--upload-s3", action="store_true", help="Upload output XML files to S3")
    parser.add_argument("--s3-bucket", type=str, help="S3 bucket to upload to")
    parser.add_argument("--cleanup", action="store_true", help="Remove local files after processing")
    parser.add_argument("--cleanup-s3", action="store_true", help="Remove s3 files after processing (using CSV)")
    parser.add_argument("--csv-name", type=str, default=None, help="Custom name for CSV file when uploading to S3")
    parser.add_argument("--goods-percent", type=int, default=0, help="Percentage of files with custom goods descriptions")
    parser.add_argument("--save-pdf", action="store_true", help="Also save generated PDFs locally next to XMLs")
    # Multi-attachment controls
    parser.add_argument("--attachments-total-mb", type=float, default=2.0,
                        help="Total MB budget for ALL attachments per XML (≤ 10 MB)")
    parser.add_argument("--attachment-max-mb", type=float, default=2.0,
                        help="Max MB per attachment (≤ 2 MB)")
    # Percentage of XMLs with NO attachments at all
    parser.add_argument("--no-attachments-percent", type=int, default=0,
                        help="Percentage (0-100) of XMLs to generate with NO attachments")
    # Base XML controls
    parser.add_argument("--base-xml", type=str, default="IE3F32.xml",
                        help="Default base XML file (used unless alternate is selected)")
    parser.add_argument("--alt-base-xml", type=str, default=None,
                        help="Alternate base XML file (optional), e.g., IE3F43.xml")
    parser.add_argument("--alt-base-percent", type=int, default=0,
                        help="Percentage (0-100) of XMLs that should use --alt-base-xml")

    args = parser.parse_args()

    # Validate percentages
    if args.no_attachments_percent < 0 or args.no_attachments_percent > 100:
        raise ValueError("--no-attachments-percent must be between 0 and 100")
    if args.alt_base_percent < 0 or args.alt_base_percent > 100:
        raise ValueError("--alt-base-percent must be between 0 and 100")
    if args.alt_base_percent > 0 and not args.alt_base_xml:
        raise ValueError("--alt-base-percent was set but --alt-base-xml is missing")

    num_files = int(os.getenv("NUM_FILES", args.num))
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # CSV name default
    csv_name = args.csv_name if args.csv_name else f"/test_xmls/jmeter_data_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"

    # Enforce caps for multi-attachment mode
    args.attachment_max_mb, args.attachments_total_mb = _effective_caps(args.attachment_max_mb, args.attachments_total_mb)

    results = []

    if not args.cleanup and not args.cleanup_s3:
        with ProcessPoolExecutor() as executor:
            worker = partial(
                generate_and_update,
                base_xml=args.base_xml,
                alt_base_xml=args.alt_base_xml,
                alt_base_percent=args.alt_base_percent,
                goods_percent=args.goods_percent,
                save_pdf=args.save_pdf,
                attachments_total_mb=args.attachments_total_mb,
                attachment_max_mb=args.attachment_max_mb,
                no_attachments_percent=args.no_attachments_percent
            )
            results = list(executor.map(worker, range(num_files)))

        file_exists = os.path.isfile(csv_name)

        updated_results = []
        for (xml_filename, xml_buffer, message_id, lrn, timestamp,
             has_attachments, attachment_count, total_mb_used, base_xml_used) in results:
            if args.upload_s3:
                filepath = f"s3://{args.s3_bucket}/test_xmls/{xml_filename}"
            else:
                filepath = os.path.join(OUTPUT_DIR.lstrip('/'), xml_filename)
                if not args.cleanup and not args.cleanup_s3:
                    with open(os.path.join(OUTPUT_DIR, xml_filename), "wb") as f:
                        f.write(xml_buffer.getvalue())
                    print(f"Saved XML to {os.path.join(OUTPUT_DIR, xml_filename)}")

            updated_results.append((
                xml_filename, filepath, message_id, lrn, timestamp,
                "true" if has_attachments else "false",
                attachment_count,
                total_mb_used,
                base_xml_used
            ))

        with open(csv_name, mode="a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "filename", "filepath", "messageId", "lrn", "timestamp",
                    "hasAttachments", "attachmentCount", "attachmentsTotalMB", "baseXml"
                ])
            writer.writerows(updated_results)

        print(f"JMeter CSV saved: {csv_name}")

    s3_keys = []

    if args.upload_s3:
        if not args.s3_bucket:
            print("--s3-bucket is required when using --upload-s3")
            return

        for xml_filename, xml_buffer, *_ in results:
            key = f"test_xmls/{xml_filename}"
            s3_keys.append(key)
            upload_to_s3_from_memory(buffer=xml_buffer, bucket_name=args.s3_bucket, key=key)

        upload_to_s3(csv_name, args.s3_bucket, csv_name)
        print(f"Uploaded {csv_name} to s3://{args.s3_bucket}/{csv_name}")

    if args.cleanup_s3:
        if not args.s3_bucket:
            print("--s3-bucket is required with --cleanup-s3")
            return

        if not args.csv_name:
            print("--csv-name is required with --cleanup-s3")
            return

        download_csv_from_s3(args.s3_bucket, args.csv_name, f"downloaded_{args.csv_name}.csv")
        cleanup_s3_from_csv(args.s3_bucket, f"downloaded_{args.csv_name}.csv")
        delete_csv_from_s3(args.s3_bucket, args.csv_name)

        if os.path.exists(f"downloaded_{args.csv_name}.csv"):
            os.remove(f"downloaded_{args.csv_name}.csv")
            print(f"Also deleted the downloaded CSV: downloaded_{args.csv_name}.csv")

    if args.cleanup:
        print("Cleaning up local files...")
        if os.path.exists(OUTPUT_DIR):
            shutil.rmtree(OUTPUT_DIR)
        if os.path.exists(csv_name):
            os.remove(csv_name)
            print(f"Deleted local CSV: {csv_name}")


if __name__ == "__main__":
    main()
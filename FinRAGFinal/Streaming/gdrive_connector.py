import pathway as pw
import os
import sys
import logging

import dotenv
dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Setup logging to both file and console with immediate flush
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('gdrive_streaming.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.getenv("HOME_FILE_PATH"))

from main import FinRAGPipeline

# Initialize the pipeline
logger.info("Initializing FinRAG Pipeline...")
pipeline = FinRAGPipeline()
logger.info("FinRAG Pipeline initialized successfully!")

folder_id = "1GKw-BXYEZtV1IAZbCpPvwK0wLaqfXb0X"
credentials_file = "Streaming/user_cred.json"
download_dir = "downloaded_pdfs"

# Create download directory if it doesn't exist
os.makedirs(download_dir, exist_ok=True)

# 1. STREAM FILES FROM GOOGLE DRIVE
files = pw.io.gdrive.read(
    object_id=folder_id,
    service_user_credentials_file=credentials_file,
    mode="streaming",
    with_metadata=True,
    refresh_interval=10  # returns columns: data, _metadata
)



# 3. DOWNLOAD PDFs DIRECTLY FROM DATA
@pw.udf
def save_pdf(data: bytes, metadata: pw.Json) -> str:
    name = metadata.value["name"]  # Use .value to access the actual dict
    local_path = os.path.join(download_dir, name)
    with open(local_path, "wb") as f:
        f.write(data)
    logger.info(f"Downloaded: {name} → {local_path}")
    logger.info("Updating FinRAG with the new file...")
    sys.stdout.flush()  # Force output
    
    try:
        pipeline.update_tree_file(local_path)
        logger.info(f"Successfully updated tree with: {name}")
    except Exception as e:
        logger.error(f"Error updating tree with {name}: {e}")
    
    sys.stdout.flush()  # Force output after update
    return local_path

processed = files.select(
    name=pw.this._metadata["name"],
    url=pw.this._metadata["url"],
    local_path=save_pdf(pw.this.data, pw.this._metadata)
)

# 4. WRITE TO CSV
pw.io.csv.write(processed, "gdrive_files.csv")

pw.run()
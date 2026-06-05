"""
services/mongodb_service.py
============================
MongoDB data-access layer.

All connection parameters (host, port, username, password) are fetched from
AWS Secrets Manager via `get_secret()`. No credentials appear in this file.

Collections:
  - documents:  Metadata for every uploaded file.

MongoDB document schema (documents collection):
{
    "_id":           ObjectId,
    "filename":      str   — UUID-based S3 object key filename,
    "original_name": str   — Original file name as submitted by the user,
    "s3_key":        str   — Full S3 object key (prefix/filename),
    "file_size":     int   — File size in bytes,
    "upload_date":   datetime (UTC),
    "uploader":      str   — Uploader's email address,
    "content_type":  str   — MIME type (e.g. "application/pdf"),
    "description":   str   — Optional description entered by the user
}
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from pymongo import MongoClient, DESCENDING
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, OperationFailure

from services.secrets_manager import get_secret

logger = logging.getLogger(__name__)

# ── Singleton client ───────────────────────────────────────────────────────────
_client: Optional[MongoClient] = None
_db = None

DB_NAME = "employee_portal"
DOCUMENTS_COLLECTION = "documents"


def _get_db():
    """
    Return the MongoDB database handle.
    Initialises the MongoClient singleton on first call using
    credentials and host information from AWS Secrets Manager.
    """
    global _client, _db

    if _client is None:
        host = get_secret("mongodb_host")
        port = int(get_secret("mongodb_port"))
        username = get_secret("mongodb_username")
        password = get_secret("mongodb_password")

        mongo_uri = (
            f"mongodb://{username}:{password}@{host}:{port}/"
            f"{DB_NAME}?authSource=admin"
        )

        logger.info("Connecting to MongoDB at %s:%d …", host, port)

        _client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )

        # Verify connectivity immediately
        try:
            _client.admin.command("ping")
            logger.info("MongoDB connection established.")
        except ConnectionFailure as exc:
            _client = None
            raise RuntimeError(
                f"Unable to connect to MongoDB at {host}:{port}. "
                "Check network/security group rules and that mongod is running."
            ) from exc

        _db = _client[DB_NAME]

    return _db


def _documents_col() -> Collection:
    """Return the documents collection handle."""
    return _get_db()[DOCUMENTS_COLLECTION]


# ── Document CRUD ──────────────────────────────────────────────────────────────

def insert_document_metadata(
    filename: str,
    original_name: str,
    s3_key: str,
    file_size: int,
    uploader: str,
    content_type: str,
    description: str = "",
) -> str:
    """
    Insert a new document metadata record into MongoDB.

    Returns:
        The inserted document's string ID.
    """
    doc = {
        "filename": filename,
        "original_name": original_name,
        "s3_key": s3_key,
        "file_size": file_size,
        "upload_date": datetime.now(tz=timezone.utc),
        "uploader": uploader,
        "content_type": content_type,
        "description": description,
    }
    result = _documents_col().insert_one(doc)
    logger.info("Document metadata saved [id=%s, name=%s].", result.inserted_id, original_name)
    return str(result.inserted_id)


def get_all_documents(search: str = "") -> list[dict]:
    """
    Retrieve all document metadata records, optionally filtered by a
    case-insensitive substring search on the original file name.

    Returns:
        List of document dicts (most recent first).
    """
    query = {}
    if search:
        query["original_name"] = {"$regex": search, "$options": "i"}

    cursor = _documents_col().find(query).sort("upload_date", DESCENDING)
    docs = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        docs.append(doc)
    return docs


def get_recent_documents(n: int = 5) -> list[dict]:
    """
    Return the *n* most recently uploaded documents.
    """
    cursor = _documents_col().find().sort("upload_date", DESCENDING).limit(n)
    docs = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        docs.append(doc)
    return docs


def get_document_by_id(doc_id: str) -> Optional[dict]:
    """
    Fetch a single document by its string ID.

    Returns:
        The document dict, or None if not found.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        oid = ObjectId(doc_id)
    except InvalidId:
        logger.warning("Invalid ObjectId: '%s'", doc_id)
        return None

    doc = _documents_col().find_one({"_id": oid})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def get_total_documents() -> int:
    """Return the total number of documents in the collection."""
    return _documents_col().count_documents({})


def get_total_storage_bytes() -> int:
    """Return the sum of all document file sizes in bytes."""
    pipeline = [{"$group": {"_id": None, "total": {"$sum": "$file_size"}}}]
    result = list(_documents_col().aggregate(pipeline))
    return result[0]["total"] if result else 0

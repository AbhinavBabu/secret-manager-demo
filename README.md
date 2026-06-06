# DocPortal - Secure Employee Document Portal

> A production-grade, cloud-native Flask web application demonstrating
> real-world **AWS Secrets Manager** usage for secure employee document management.

---

## Architecture Overview

```
                        ┌────────────────────────────────────┐
                        │          EC2 (App Server)           │
                        │  Flask + Gunicorn  |  Port 5000     │
                        │                                      │
                        │  ┌─────────────────────────────┐   │
                        │  │  AWS Secrets Manager Client  │   │
                        │  │  (boto3 — IAM Instance Role) │   │
                        │  └──────────────┬──────────────┘   │
                        └─────────────────┼──────────────────┘
                                          │ GetSecretValue
                              ┌───────────▼───────────┐
                              │  AWS Secrets Manager   │
                              │  "employee-portal/     │
                              │   secrets"             │
                              └───────────────────────┘

    ┌─────────────────┐      ┌──────────────────┐      ┌──────────────────┐
    │ EC2 (App Server)│─────▶│   Amazon S3       │─────▶│   AWS KMS (CMK)  │
    │                 │      │  (PDF documents)  │      │  (Encryption key) │
    └────────┬────────┘      └──────────────────┘      └──────────────────┘
             │
             │ MongoDB URI (from Secrets Manager)
             ▼
    ┌─────────────────┐
    │ EC2 (MongoDB)   │
    │  Port 27017     │
    └─────────────────┘
```

---

## AWS Secrets Manager — Secret Payload

Create a single secret named **`employee-portal/secrets`** with the following JSON value:

```json
{
  "mongodb_username":    "admin",
  "mongodb_password":    "YourStrongPassword123!",
  "mongodb_host":        "10.0.x.x",
  "mongodb_port":        "27017",

  "jwt_secret_key":      "replace-with-a-long-random-string-64-chars",

  "smtp_username":       "yourcompany@gmail.com",
  "smtp_password":       "your-16-char-gmail-app-password",

  "s3_bucket_name":      "employee-documents-your-account-id",
  "kms_key_id":          "arn:aws:kms:us-east-1:ACCOUNT_ID:key/YOUR-CMK-ID",

  "admin_email":         "admin@yourcompany.com",
  "admin_password_hash": "<see step 5 below>"
}
```

> **No credentials exist anywhere in the source code.**
> All values are fetched at runtime via `boto3` using the EC2 IAM Instance Role.

---

## Deployment Guide

### Prerequisites

- AWS Account with access to EC2, S3, KMS, Secrets Manager, IAM.
- Two EC2 instances (Ubuntu 22.04 recommended):
  - **App Server** (t3.small or larger) — runs Flask.
  - **MongoDB Server** (t3.small or larger) — runs MongoDB.
- A verified Gmail account with 2-Step Verification + App Password generated.

---

### Step 1 — Create a Customer-Managed KMS Key

```bash
aws kms create-key \
  --description "Employee Document Portal CMK" \
  --region us-east-1

# Note the KeyId from the output, e.g.:
# "KeyId": "arn:aws:kms:us-east-1:123456789012:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

Give the key an alias for easy reference:

```bash
aws kms create-alias \
  --alias-name alias/employee-portal-key \
  --target-key-id <YOUR_KEY_ID> \
  --region us-east-1
```

---

### Step 2 — Create the S3 Bucket

```bash
aws s3api create-bucket \
  --bucket employee-documents-<YOUR_ACCOUNT_ID> \
  --region us-east-1

# Block all public access
aws s3api put-public-access-block \
  --bucket employee-documents-<YOUR_ACCOUNT_ID> \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# Enable default KMS encryption on the bucket
aws s3api put-bucket-encryption \
  --bucket employee-documents-<YOUR_ACCOUNT_ID> \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms",
        "KMSMasterKeyID": "<YOUR_CMK_ARN>"
      }
    }]
  }'
```

---

### Step 3 — Create IAM Role for the App EC2 Instance

Create a policy file `portal-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SecretsManagerAccess",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:employee-portal/secrets-*"
    },
    {
      "Sid": "S3DocumentAccess",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::employee-documents-ACCOUNT_ID/documents/*"
    },
    {
      "Sid": "KMSAccess",
      "Effect": "Allow",
      "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
      "Resource": "<YOUR_CMK_ARN>"
    }
  ]
}
```

```bash
# Create role + policy
aws iam create-role \
  --role-name EmployeePortalRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

aws iam put-role-policy \
  --role-name EmployeePortalRole \
  --policy-name PortalPolicy \
  --policy-document file://portal-policy.json

aws iam create-instance-profile --instance-profile-name EmployeePortalProfile
aws iam add-role-to-instance-profile --instance-profile-name EmployeePortalProfile --role-name EmployeePortalRole
```

Attach the instance profile to your App EC2 instance.

---

### Step 4 — Set Up MongoDB EC2

SSH into the MongoDB EC2 instance:

```bash
# Install MongoDB 7.0
wget -qO - https://www.mongodb.org/static/pgp/server-7.0.asc | sudo apt-key add -
echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt-get update
sudo apt-get install -y mongodb-org

sudo systemctl start mongod
sudo systemctl enable mongod

# Create admin user
mongosh --eval '
  db = db.getSiblingDB("admin");
  db.createUser({
    user: "admin",
    pwd: "YourStrongPassword123!",
    roles: ["root"]
  });
'

# Enable authentication — edit /etc/mongod.conf:
# security:
#   authorization: enabled
# net:
#   bindIp: 0.0.0.0    (or App Server private IP only)

sudo systemctl restart mongod
```

**Security group rule:** Allow port 27017 inbound only from the App Server EC2 private IP.

---

### Step 5 — Generate bcrypt Password Hash

On your local machine or App Server (with `bcrypt` installed):

```bash
pip install bcrypt
python3 -c "
import bcrypt
pw = b'YourAdminPassword123!'
hashed = bcrypt.hashpw(pw, bcrypt.gensalt()).decode()
print(hashed)
"
```

Copy the output (e.g. `$2b$12$...`) — this is your `admin_password_hash`.

---

### Step 6 — Create the Secrets Manager Secret

```bash
aws secretsmanager create-secret \
  --name "employee-portal/secrets" \
  --region us-east-1 \
  --secret-string '{
    "mongodb_username":    "admin",
    "mongodb_password":    "YourStrongPassword123!",
    "mongodb_host":        "10.0.x.x",
    "mongodb_port":        "27017",
    "jwt_secret_key":      "replace-with-a-long-random-string-64-chars",
    "smtp_username":       "yourcompany@gmail.com",
    "smtp_password":       "your-16-char-gmail-app-password",
    "s3_bucket_name":      "employee-documents-ACCOUNT_ID",
    "kms_key_id":          "arn:aws:kms:us-east-1:ACCOUNT_ID:key/YOUR-CMK-ID",
    "admin_email":         "admin@yourcompany.com",
    "admin_password_hash": "$2b$12$..."
  }'
```

---

### Step 7 — Deploy the Application on App EC2

SSH into the App EC2 instance:

```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv git

# Clone / upload your code
git clone https://github.com/YOUR_REPO/secrets_manager-demo.git /opt/employee-portal
cd /opt/employee-portal

# Create virtual environment and install packages
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Test startup (should connect to Secrets Manager, MongoDB, and log "ready")
python app.py
```

---

### Step 8 — Run with Gunicorn (Production)

```bash
# Run with 4 worker processes on port 5000
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

#### Set up as a systemd service:

```ini
# /etc/systemd/system/employee-portal.service

[Unit]
Description=Secure Employee Document Portal
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/employee-portal
Environment=FLASK_ENV=production
ExecStart=/opt/employee-portal/venv/bin/gunicorn -w 4 -b 0.0.0.0:5000 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable employee-portal
sudo systemctl start employee-portal
sudo systemctl status employee-portal
```

---

### Step 9 — Security Group Rules

| Resource       | Port | Source                      | Purpose             |
|----------------|------|-----------------------------|---------------------|
| App EC2        | 5000 | Your IP / Load Balancer SG  | Flask web access    |
| App EC2        | 22   | Your IP only                | SSH admin access    |
| MongoDB EC2    | 27017| App EC2 private IP only     | Database connection |
| MongoDB EC2    | 22   | Your IP only                | SSH admin access    |

---

### Step 10 — Verify the Deployment

1. Open `http://<APP_EC2_PUBLIC_IP>:5000` in a browser.
2. Log in with `admin_email` and the plaintext password you hashed.
3. Navigate to **Upload Document** and upload a PDF.
4. Verify:
   - The file appears in S3 with KMS encryption tag.
   - Metadata is stored in MongoDB (`employee_portal.documents` collection).
   - Admin email received an HTML notification.
   - Document appears in the **Documents** page with a working download link.

---

## MongoDB Schema Reference

**Database:** `employee_portal`  
**Collection:** `documents`

```json
{
  "_id":           "ObjectId",
  "filename":      "string  — UUID-prefixed S3 object filename",
  "original_name": "string  — Original name as submitted",
  "s3_key":        "string  — Full S3 object key (documents/YYYY/MM/DD/...)",
  "file_size":     "int     — File size in bytes",
  "upload_date":   "ISODate — UTC upload timestamp",
  "uploader":      "string  — Uploader email address",
  "content_type":  "string  — MIME type (application/pdf)",
  "description":   "string  — Optional description"
}
```

---

## Project Structure

```
secrets_manager-demo/
├── app.py                       # Flask app factory + startup
├── routes/
│   ├── __init__.py
│   ├── auth_routes.py           # /login, /logout
│   └── document_routes.py       # /dashboard, /upload, /documents, /download
├── services/
│   ├── __init__.py
│   ├── secrets_manager.py       # ★ AWS Secrets Manager singleton
│   ├── mongodb_service.py       # MongoDB CRUD
│   ├── s3_service.py            # S3 upload + pre-signed URL
│   ├── email_service.py         # SMTP notifications
│   └── auth_service.py          # JWT + bcrypt auth
├── templates/
│   ├── base.html                # Sidebar layout
│   ├── login.html               # Split-panel login
│   ├── dashboard.html           # Stats + recent uploads
│   ├── upload.html              # Drag-and-drop uploader
│   └── documents.html           # Searchable document table
├── static/
│   ├── css/style.css            # Dark navy corporate theme
│   └── js/app.js                # Client-side interactions
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Security Highlights

| Feature | Implementation |
|---|---|
| No hardcoded secrets | All secrets fetched from **AWS Secrets Manager** at runtime |
| No AWS keys in code | EC2 **IAM Instance Role** with least-privilege scoped policy |
| Encrypted storage | S3 objects encrypted with **customer-managed KMS key (CMK)** |
| Secure downloads | **Pre-signed S3 URLs** (15 min expiry) — bucket is never public |
| Auth tokens | **JWT** stored in Flask signed session cookies (not localStorage) |
| Password storage | **bcrypt** hash stored in Secrets Manager — not in database |
| MongoDB auth | Credentials retrieved from Secrets Manager, `authSource=admin` |
| SMTP auth | Gmail **App Password** stored in Secrets Manager |

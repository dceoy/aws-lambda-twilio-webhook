"""Constants for the Twilio webhook Lambda function."""

import os
from pathlib import Path

# System Configuration
SYSTEM_NAME = os.getenv("SYSTEM_NAME", "twh")
ENV_TYPE = os.getenv("ENV_TYPE", "dev")

# TwiML File Paths
TWIML_DIR = Path(__file__).parent.parent / "twiml"
CONNECT_TWIML_FILE_PATH: str = str(TWIML_DIR / "connect.twiml.xml")
DIAL_TWIML_FILE_PATH: str = str(TWIML_DIR / "dial.twiml.xml")
GATHER_TWIML_FILE_PATH: str = str(TWIML_DIR / "gather.twiml.xml")
HANGUP_TWIML_FILE_PATH: str = str(TWIML_DIR / "hangup.twiml.xml")
BIRTHDATE_TWIML_FILE_PATH: str = str(TWIML_DIR / "birthdate.twiml.xml")

# Business Logic
BIRTHDATE_DIGIT_LENGTH = 8

# HTTP Content Types
CONTENT_TYPE_XML = "application/xml"
CONTENT_TYPE_JSON = "application/json"

# HTTP Headers
TWILIO_SIGNATURE_HEADER = "X-Twilio-Signature"

# SSM Parameter Names
SSM_TWILIO_AUTH_TOKEN = "twilio-auth-token"  # noqa: S105
SSM_MEDIA_API_URL = "media-api-url"
SSM_OPERATOR_PHONE_NUMBER = "operator-phone-number"
SSM_WEBHOOK_API_URL = "webhook-api-url"

# DTMF Digits
DTMF_VOICE_ASSISTANT = "1"
DTMF_OPERATOR_TRANSFER = "2"

# URL Paths
HEALTH_ENDPOINT = "/health"
TRANSFER_CALL_ENDPOINT = "/transfer-call"
INCOMING_CALL_ENDPOINT = "/incoming-call/<twiml_file_stem>"
PROCESS_BIRTHDATE_PATH = "/process-birthdate"
CONFIRM_BIRTHDATE_PATH = "/confirm-birthdate"

# URL Components
HTTPS_SCHEME = "https://"
URL_QUERY_SEPARATOR = "?"

# Form Parameter Names
FORM_PARAM_DIGITS = "Digits"
FORM_PARAM_FROM = "From"

# AWS Service Names
AWS_SSM_SERVICE = "ssm"

# Error Messages
ERROR_DIGITS_NOT_FOUND = "Digits not found in the request body"
ERROR_BIRTHDATE_DIGITS_NOT_FOUND = "Birth date digits not found in the request"
ERROR_CALL_NUMBER_NOT_FOUND = "Call number not found in the request body"
ERROR_MISSING_TWILIO_SIGNATURE = "Missing X-Twilio-Signature header"
ERROR_INVALID_TWILIO_SIGNATURE = "Invalid Twilio request signature"
ERROR_INVALID_PARAMETERS = "Invalid parameters: {}"

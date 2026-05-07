import os

DSN_NAME = os.getenv('DB_DSN', '')
DB_USER = os.getenv('DB_USER', '')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
COMPANY_NAME = os.getenv('COMPANY_NAME', '')
SECRET_KEY = os.getenv('SECRET_KEY', '')

TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_MESSAGING_SERVICE_SID = os.getenv('TWILIO_MESSAGING_SERVICE_SID', '')
# When set, all outbound SMS are redirected to this number (dev/testing only)
DEV_SMS_OVERRIDE = os.getenv('DEV_SMS_OVERRIDE', '')

VAPID_PUBLIC_KEY  = os.getenv('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '')
VAPID_EMAIL       = os.getenv('VAPID_EMAIL', '')

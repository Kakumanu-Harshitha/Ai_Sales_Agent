import os
import sys
import traceback
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from apps.api.core.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar"
]

TOKEN_PATH = os.path.join(os.getcwd(), "apps", "api", "storage", "oauth", "token.json")

def get_google_credentials() -> Credentials:
    print("Entering get_google_credentials()")
    cwd = os.getcwd()
    print(f"Current Working Directory: {cwd}")
    
    config_path = settings.GOOGLE_CREDENTIALS_PATH
    print(f"Configured Credentials Path: {config_path}")
    
    abs_path = os.path.abspath(config_path)
    print(f"Absolute Credentials Path: {abs_path}")
    
    print(f"credentials.json exists: {'YES' if os.path.exists(abs_path) else 'NO'}")
    
    if os.path.exists(abs_path):
        try:
            import json
            with open(abs_path, 'r') as f:
                creds_data = json.load(f)
            # Support both 'installed' and 'web' client types
            client_type = 'installed' if 'installed' in creds_data else 'web' if 'web' in creds_data else None
            if client_type:
                client_id = creds_data[client_type].get('client_id', '')
                project_id = creds_data[client_type].get('project_id', '')
                masked_client = f"{client_id[:10]}...{client_id[-10:]}" if len(client_id) > 20 else client_id
                print(f"Client ID: {masked_client}")
                print(f"Project ID: {project_id}")
            else:
                print("Could not find 'installed' or 'web' keys in credentials.json.")
        except Exception as e:
            print("Failed to parse credentials.json for debug info.")
            traceback.print_exc()
            
    print("Checking token.json...")
    print(f"token.json exists: {'YES' if os.path.exists(TOKEN_PATH) else 'NO'}")
    
    creds = None
    if os.path.exists(TOKEN_PATH):
        print("Loading credentials...")
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
            print("Token loaded successfully.")
        except Exception as e:
            print("Failed to load token.json!")
            traceback.print_exc()
            creds = None
            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Token expired.")
            print("Refreshing token...")
            try:
                creds.refresh(Request())
                print("Refresh successful.")
            except Exception as e:
                print("Refresh failed! Traceback:")
                traceback.print_exc()
                creds = None
                
        if not creds or not creds.valid:
            if not os.path.exists(abs_path):
                print(f"CRITICAL ERROR: credentials.json not found at {abs_path}")
                raise FileNotFoundError(f"credentials.json not found at {abs_path}")
                
            print("Starting InstalledAppFlow...")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(abs_path, SCOPES)
            except Exception as e:
                print("Failed to initialize InstalledAppFlow. Traceback:")
                traceback.print_exc()
                raise
                
            print("Opening browser...")
            print("Waiting for OAuth callback...")
            try:
                creds = flow.run_local_server(
                    port=0,
                    access_type='offline',
                    prompt='consent'
                )
            except Exception as e:
                print("Failed during run_local_server (browser launch or auth). Traceback:")
                traceback.print_exc()
                raise
                
            print("Authentication successful.")
            
            print("Saving token.json...")
            os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
            with open(TOKEN_PATH, 'w') as token_file:
                token_file.write(creds.to_json())
            
    print("Returning credentials.")
    if creds:
        print(f"Granted Scopes: {', '.join(creds.scopes) if creds.scopes else 'Unknown'}")
        print(f"Token Expiry: {creds.expiry}")
        
    return creds


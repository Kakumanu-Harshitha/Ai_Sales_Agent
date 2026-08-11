import os
import json
import base64
from email.message import EmailMessage
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from apps.api.core.google_auth import get_google_credentials

def get_gmail_service():
    creds = get_google_credentials()
    if not creds:
        raise Exception("Google credentials not found or invalid.")
    return build('gmail', 'v1', credentials=creds)

def send_email_via_gmail(to: str, subject: str, body: str, html_body: str = None, inline_images: dict = None) -> str:
    """
    Sends an email using the Gmail API.
    Returns the Gmail Message ID.
    Raises Exception with error details if failed.
    """
    try:
        service = get_gmail_service()
        # Get authenticated email for the From header
        profile = service.users().getProfile(userId='me').execute()
        from_email = profile.get('emailAddress')
        
        message = EmailMessage()
        message.set_content(body)
        
        if html_body:
            message.add_alternative(html_body, subtype='html')
            if inline_images:
                html_part = message.get_payload()[1]
                import mimetypes
                for cid, file_path in inline_images.items():
                    if os.path.exists(file_path):
                        with open(file_path, 'rb') as f:
                            img_data = f.read()
                        mt, st = (mimetypes.guess_type(file_path)[0] or 'application/octet-stream').split('/', 1)
                        html_part.add_related(img_data, maintype=mt, subtype=st, cid=f"<{cid}>")
            
        message['To'] = to
        message['From'] = from_email
        message['Subject'] = subject
        
        from email.utils import make_msgid, formatdate
        message['Date'] = formatdate(localtime=True)
        domain = from_email.split('@')[1] if '@' in from_email else None
        message['Message-ID'] = make_msgid(domain=domain)

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {'raw': encoded_message}

        send_message = (service.users().messages().send(userId="me", body=create_message).execute())
        
        return send_message['id']
    except HttpError as error:
        raise Exception(f"Gmail API HttpError: {error}")
    except Exception as e:
        raise Exception(f"Failed to send email: {e}")

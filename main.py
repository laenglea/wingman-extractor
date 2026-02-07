import os
import grpc
import tempfile
import mimetypes
import extract_msg
import email
import email.policy

from concurrent import futures
from grpc_reflection.v1alpha import reflection

from openai import OpenAI
from markitdown import MarkItDown
from markdownify import markdownify

import extractor_pb2
import extractor_pb2_grpc

llm_client = None
llm_model = os.getenv("OPENAI_MODEL")

openai_url = os.getenv("OPENAI_BASE_URL")
openai_api_key = os.getenv("OPENAI_API_KEY")

if openai_url or openai_api_key:
    llm_client = OpenAI(api_key=openai_api_key, base_url=openai_url)

markitdown = MarkItDown(llm_model=llm_model, llm_client=llm_client)

def extract_msg_content(file_path: str) -> str:
    """Extract content from MSG file using msg-extractor."""
    msg = extract_msg.Message(file_path)
    
    content_parts = []
    
    content_parts.append(f"# {msg.subject or '(No Subject)'}")
    
    for field, label in [('sender', 'From'), ('to', 'To'), ('cc', 'CC'), ('bcc', 'BCC'), ('date', 'Date')]:
        if value := getattr(msg, field, None):
            content_parts.append(f"**{label}:** {value}")
    
    content_parts.append("")  # Empty line before body
    
    if msg.body:
        body = msg.body.strip()
        content_parts.append(body)
    elif msg.htmlBody:
        body = msg.htmlBody.decode('utf-8', errors='ignore')
        body = markdownify(body, heading_style="ATX")
        content_parts.append(body)
    
    # Extract attachments info
    # if msg.attachments:
    #     content_parts.append("\n## Attachments")
    #     for attachment in msg.attachments:
    #         if hasattr(attachment, 'longFilename') and attachment.longFilename:
    #             content_parts.append(f"- {attachment.longFilename}")
    #         elif hasattr(attachment, 'shortFilename') and attachment.shortFilename:
    #             content_parts.append(f"- {attachment.shortFilename}")
    
    return "\n".join(content_parts)

def extract_eml_content(file_path: str) -> str:
    """Extract content from EML file using Python's email module."""
    with open(file_path, 'rb') as f:
        msg = email.message_from_bytes(f.read(), policy=email.policy.default)
    
    content_parts = []
    
    content_parts.append(f"# {msg.get('Subject') or '(No Subject)'}")
    
    for field, label in [('From', 'From'), ('To', 'To'), ('Cc', 'CC'), ('Bcc', 'BCC'), ('Date', 'Date')]:
        if value := msg.get(field):
            content_parts.append(f"**{label}:** {value}")
    
    content_parts.append("")  # Empty line before body
    
    # Extract body content
    body_content = ""
    
    if msg.is_multipart():
        # Handle multipart messages
        for part in msg.walk():
            content_type = part.get_content_type()
            
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or 'utf-8'
                    body_content = payload.decode(charset, errors='ignore')
                else:
                    body_content = str(payload)
                break
            elif content_type == "text/html" and not body_content:
                # Use HTML as fallback if no plain text found
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or 'utf-8'
                    html_content = payload.decode(charset, errors='ignore')
                else:
                    html_content = str(payload)
                body_content = markdownify(html_content, heading_style="ATX")
    else:
        # Handle single part messages
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        
        if content_type == "text/plain":
            if isinstance(payload, bytes):
                body_content = payload.decode('utf-8', errors='ignore')
            else:
                body_content = str(payload)
        elif content_type == "text/html":
            if isinstance(payload, bytes):
                html_content = payload.decode('utf-8', errors='ignore')
            else:
                html_content = str(payload)
            body_content = markdownify(html_content, heading_style="ATX")
    
    if body_content:
        content_parts.append(body_content.strip())
    
    # Extract attachment information
    # if msg.is_multipart():
    #     attachments = []
    #     for part in msg.walk():
    #         if part.get_content_disposition() == 'attachment':
    #             filename = part.get_filename()
    #             if filename:
    #                 attachments.append(filename)
    #     
    #     if attachments:
    #         content_parts.append("\n## Attachments")
    #         for filename in attachments:
    #             content_parts.append(f"- {filename}")
    
    return "\n".join(content_parts)

class ExtractorServicer(extractor_pb2_grpc.ExtractorServicer):
    def Extract(self, request: extractor_pb2.ExtractRequest, context: grpc.ServicerContext):
        file = request.file

        if not file:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details('File is required but not provided')
            return extractor_pb2.File()

        if file.name:
            file_name = file.name
            file_ext = os.path.splitext(file.name)[1].lower()
        else:
            file_ext = mimetypes.guess_extension(file.content_type) or '.tmp'
            file_name = "input" + file_ext


        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, file_name)

            with open(file_path, "wb") as temp_file:
                temp_file.write(file.content)
            
            # Check if it's an MSG file or EML file and handle it specially
            if file_ext == '.msg':
                text_content = extract_msg_content(file_path)
            elif file_ext == '.eml':
                text_content = extract_eml_content(file_path)
            else:
                result = markitdown.convert(file_path)
                text_content = result.text_content

            return extractor_pb2.Document(text=text_content)

def serve():
    max_message_size = 100 * 1024 * 1024

    options = [
        ('grpc.max_receive_message_length', max_message_size),
        ('grpc.max_send_message_length', max_message_size),
    ]

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=options
    )

    extractor = ExtractorServicer()
    extractor_pb2_grpc.add_ExtractorServicer_to_server(extractor, server)

    SERVICE_NAMES = (
        extractor_pb2.DESCRIPTOR.services_by_name['Extractor'].full_name,
        reflection.SERVICE_NAME,
    )

    reflection.enable_server_reflection(SERVICE_NAMES, server)

    server.add_insecure_port('[::]:50051')
    server.start()

    print("Wingman Extractor started. Listening on port 50051.")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
import os
import grpc
import tempfile
import mimetypes

from concurrent import futures
from grpc_reflection.v1alpha import reflection

from openai import OpenAI
from markitdown import MarkItDown

import extractor_pb2
import extractor_pb2_grpc

llm_client = None
llm_model = os.getenv("OPENAI_MODEL")

openai_url = os.getenv("OPENAI_BASE_URL")
openai_api_key = os.getenv("OPENAI_API_KEY")

if openai_url or openai_api_key:
    llm_client = OpenAI(api_key=openai_api_key, base_url=openai_url)

markitdown = MarkItDown(llm_model=llm_model, llm_client=llm_client)

class ExtractorServicer(extractor_pb2_grpc.ExtractorServicer):
    def Extract(self, request: extractor_pb2.ExtractRequest, context: grpc.aio.ServicerContext):
        file = request.file
        format = request.format or extractor_pb2.FORMAT_TEXT

        if not file:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details('File is required but not provided')
            return extractor_pb2.File()
        
        if format is not extractor_pb2.FORMAT_TEXT:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details('Format must be FORMAT_TEXT')
            return extractor_pb2.File()
        
        file_ext = mimetypes.guess_extension(file.content_type) or '.tmp'
        file_name = "input" + file_ext

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, file_name)

            with open(file_path, "wb") as temp_file:
                temp_file.write(file.content)
            
            result = markitdown.convert(file_path)
            data = bytes(result.text_content, 'utf-8')

            with open('page.md', 'wb') as f:
                f.write(data)

            return extractor_pb2.File(content=data, content_type='text/markdown')

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
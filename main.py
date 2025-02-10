import os
import tempfile
import uvicorn

from fastapi import FastAPI, Form, HTTPException, Response, UploadFile
from openai import OpenAI
from markitdown import MarkItDown

app = FastAPI(
    title="LLM Platform Extractor"
)

llm_client = None
llm_model = os.getenv("OPENAI_MODEL")

openai_url = os.getenv("OPENAI_BASE_URL")
openai_api_key = os.getenv("OPENAI_API_KEY")

if openai_url or openai_api_key:
    llm_client = OpenAI(api_key=openai_api_key, base_url=openai_url)

markitdown = MarkItDown(llm_model=llm_model, llm_client=llm_client)

@app.post("/")
async def create_upload_file(file: UploadFile = None, files: UploadFile = None, format: str = Form("markdown")):
    file = file or files
    
    file_name = file.filename
    file_content = await file.read()

    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = os.path.join(temp_dir, file_name)
    
        with open(file_path, "wb") as temp_file:
            temp_file.write(file_content)
        
        match format:
            case "text" | "markdown":
                try:
                    result = markitdown.convert(file_path)

                    return [
                        {
                            "title": result.title,
                            "text": result.text_content
                        }
                    ]
                except Exception as e:
                    app.logger.error(f"Error processing file {file_name}: {e}")
                    raise HTTPException(status_code=500, detail="Internal server error")
            
            case _:
                raise HTTPException(status_code=400, detail="Invalid format")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
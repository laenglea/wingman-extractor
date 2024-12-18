import os
import tempfile
import uvicorn

from fastapi import FastAPI, Form, HTTPException, Response, UploadFile
from markitdown import MarkItDown

app = FastAPI(
    title="LLM Platform Extractor"
)

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
                markitdown = MarkItDown()
                result = markitdown.convert(file_path)
                
                return [
                    {
                        "text": result.text_content
                    }
                ]
            
            case _:
                raise HTTPException(status_code=400, detail="Invalid format")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
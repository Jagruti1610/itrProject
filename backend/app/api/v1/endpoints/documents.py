import os
import shutil
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from ....core.database import get_db
from ....core.security import get_current_user
from ....core.config import settings
from ....models.user import User
from ....models.document import Document, DocumentStatus
from ....models.chat import Chat
from ....schemas.document import DocumentResponse, ChatRequest, ChatResponse
from ....services import gemini

# ---- OCR & PDF Libraries ----
import pytesseract
from pdf2image import convert_from_path
from pypdf import PdfReader
from PIL import Image

# Configure Tesseract
pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_PATH

router = APIRouter(prefix="/documents", tags=["Documents"])

# Helper: Extract text from PDF (handles both text-based and scanned)
def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        
        # If no text found (scanned PDF), use OCR
        if not text.strip():
            images = convert_from_path(file_path, poppler_path=settings.POPPLER_PATH)
            for img in images:
                # Use 'eng' for English. Change to 'eng+hin' if you install Hindi later.
                ocr_text = pytesseract.image_to_string(img, lang="eng")
                text += ocr_text + "\n"
    except Exception as e:
        raise Exception(f"Failed to process PDF: {str(e)}")
    return text

# Helper: Extract text from Image
def extract_text_from_image(file_path: str) -> str:
    try:
        img = Image.open(file_path)
        # Use 'eng' for English. Change to 'eng+hin' if you install Hindi later.
        text = pytesseract.image_to_string(img, lang="eng")
        return text
    except Exception as e:
        raise Exception(f"Failed to process Image: {str(e)}")

@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    model_choice: str = Form("flash"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Validate file type
    allowed_extensions = [".pdf", ".jpg", ".jpeg", ".png"]
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported file format. Use PDF, JPG, or PNG.")
    
    # Create unique filename
    unique_id = str(uuid.uuid4())
    temp_filename = f"{unique_id}_{file.filename}"
    temp_path = os.path.join("temp", temp_filename)
    
    os.makedirs("temp", exist_ok=True)
    os.makedirs("uploads", exist_ok=True)
    
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Extract text
    try:
        if ext == ".pdf":
            extracted_text = extract_text_from_pdf(temp_path)
        else:
            extracted_text = extract_text_from_image(temp_path)
    except Exception as e:
        os.remove(temp_path)
        raise HTTPException(status_code=500, detail=f"OCR failed: {str(e)}")
    
    # Create DB entry
    new_doc = Document(
        user_id=current_user.id,
        filename=file.filename,
        file_path=temp_path,
        extracted_text=extracted_text,
        status=DocumentStatus.PROCESSING,
        model_used=model_choice
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    
    # Generate Summary
    try:
        summary = gemini.generate_summary(extracted_text, model_choice)
        new_doc.summary = summary
        new_doc.status = DocumentStatus.COMPLETED
        db.commit()
        db.refresh(new_doc)
    except Exception as e:
        new_doc.status = DocumentStatus.FAILED
        db.commit()
        os.remove(temp_path)
        raise HTTPException(status_code=500, detail=f"AI Summarization failed: {str(e)}")
    
    # Move to permanent storage
    permanent_path = os.path.join("uploads", temp_filename)
    shutil.move(temp_path, permanent_path)
    new_doc.file_path = permanent_path
    db.commit()
    
    return new_doc

@router.post("/{doc_id}/chat", response_model=ChatResponse)
async def chat_with_doc(
    doc_id: int,
    chat_request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if doc.status != DocumentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Document processing is not complete yet.")
    
    context = f"Summary: {doc.summary}\n\nFull Text: {doc.extracted_text}"
    
    try:
        answer = gemini.chat_with_document(
            chat_request.question, 
            context, 
            chat_request.model_choice
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Chat failed: {str(e)}")
    
    new_chat = Chat(
        user_id=current_user.id,
        document_id=doc.id,
        question=chat_request.question,
        answer=answer
    )
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)
    
    return new_chat

@router.get("/", response_model=list[DocumentResponse])
async def get_user_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    docs = db.query(Document).filter(Document.user_id == current_user.id).order_by(Document.created_at.desc()).all()
    return docs

# ---------- NEW: Delete Document ----------
@router.delete("/{doc_id}")
async def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Delete the physical file if it exists
    if doc.file_path and os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    
    # Delete associated chats
    db.query(Chat).filter(Chat.document_id == doc.id).delete()
    
    # Delete document
    db.delete(doc)
    db.commit()
    
    return {"message": "Document and associated chat history deleted successfully"}
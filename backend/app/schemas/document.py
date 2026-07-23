from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

class DocumentStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class DocumentResponse(BaseModel):
    id: int
    filename: str
    summary: Optional[str] = None
    status: DocumentStatus
    model_used: str
    created_at: datetime

    class Config:
        from_attributes = True

class ChatRequest(BaseModel):
    question: str
    model_choice: Optional[str] = "flash"

class ChatResponse(BaseModel):
    question: str
    answer: str
    created_at: datetime
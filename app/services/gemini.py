import google.generativeai as genai
from ..core.config import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

def get_gemini_model(model_name: str = "flash"):
    if model_name == "pro":
        return genai.GenerativeModel("gemini-1.5-pro")
    else:
        return genai.GenerativeModel("gemini-1.5-flash")

def generate_summary(text: str, model_choice: str = "flash") -> str:
    model = get_gemini_model(model_choice)
    
    prompt = f"""
    You are a highly skilled legal assistant. Analyze the following legal document text and provide a structured summary.
    Format your response with these exact headings:
    
    **Facts:** (Briefly list the key facts)
    **Issues:** (What legal questions are being raised?)
    **Judgment:** (What was the final decision?)
    **Ratio Decidendi:** (The legal principle/reasoning behind the decision)
    **Conclusion:** (Final summary in 2-3 sentences)
    
    Document Text:
    {text[:100000]}
    """
    
    response = model.generate_content(prompt)
    return response.text

def chat_with_document(question: str, context_text: str, model_choice: str = "flash") -> str:
    model = get_gemini_model(model_choice)
    
    prompt = f"""
    You are a legal AI assistant. Answer the user's question based ONLY on the provided legal document text below.
    If the answer is not found in the document, strictly say "I cannot find this information in the provided document."
    Do not make up information.
    
    Document Context:
    {context_text[:150000]}
    
    User Question: {question}
    
    Answer:
    """
    
    response = model.generate_content(prompt)
    return response.text
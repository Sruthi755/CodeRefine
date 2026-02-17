import os
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
try:
    from google import genai
except Exception:
    genai = None
try:
    from groq import Groq
except Exception:
    Groq = None
try:
    from transformers import pipeline
except Exception:
    pipeline = None

# 1. Load Environment Variables

load_dotenv()

# Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Placeholders for clients/models; we'll initialize them on startup to avoid hard failures
security_scanner = None
gemini_client = None
groq_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize clients and models
    global security_scanner, gemini_client, groq_client
    # Initialize security scanner (if transformers available)
    # Skip for now since it heavily blocks startup; can be loaded on-demand per request
    if False and pipeline is not None:  # Disabled to avoid blocking startup
        try:
            logger.info("Loading Hugging Face security model... this may take a moment")
            security_scanner = pipeline(
                "text-classification",
                model="mrm8488/codebert-base-finetuned-detect-insecure-code",
            )
        except Exception as e:
            logger.exception("Failed to load security scanner: %s", e)
            security_scanner = None
    else:
        logger.warning("transformers.pipeline not available; security scanner disabled")

    # Initialize Gemini client if available and key present
    gemini_key = os.getenv("GEMINI_API_KEY")
    if genai is not None and gemini_key:
        try:
            gemini_client = genai.Client(api_key=gemini_key)
        except Exception as e:
            logger.exception("Failed to initialize Gemini client: %s", e)
            gemini_client = None
    else:
        if genai is None:
            logger.warning("google-genai SDK not installed; Gemini client disabled")
        else:
            logger.warning("GEMINI_API_KEY not set; Gemini client disabled")

    # Initialize Groq client if available and key present
    groq_key = os.getenv("GROQ_API_KEY")
    if Groq is not None and groq_key:
        try:
            groq_client = Groq(api_key=groq_key)
        except Exception as e:
            logger.exception("Failed to initialize Groq client: %s", e)
            groq_client = None
    else:
        if Groq is None:
            logger.warning("groq SDK not installed; Groq client disabled")
        else:
            logger.warning("GROQ_API_KEY not set; Groq client disabled")
    
    yield
    
    # Shutdown: Cleanup if needed (optional)
    logger.info("Shutting down OptiCode backend")


app = FastAPI(lifespan=lifespan)

# 2. Allow Frontend Communication (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend static files (index.html + assets)
# Frontend is located sibling to backend in ../frontend
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if not os.path.isdir(static_dir):
    logger.warning("Frontend directory not found at %s. Static files won't be served.", static_dir)
else:
    # Mount static files under /static to avoid shadowing API routes
    app.mount("/static", StaticFiles(directory=static_dir), name="frontend")

    # Serve index.html at root
    @app.get("/", include_in_schema=False)
    def serve_index():
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Index not found")

# 4. Data Structure
class CodePayload(BaseModel):
    code: str
    model: str = "gemini" 

# 5. The Analysis Endpoint
@app.post("/analyze")
async def analyze_code(payload: CodePayload):
    try:
        # Step A: Local Security Scan (best-effort)
        if security_scanner is not None and payload.code:
            try:
                hf_result = security_scanner(payload.code[:512])
                raw_label = hf_result[0].get('label', '')
                status = "insecure" if raw_label == "LABEL_1" else "secure"
            except Exception:
                logger.exception("Security scanner failed during analysis")
                status = "unknown"
        else:
            status = "unknown"

        # Step B: Prepare the Prompt
        prompt = f"""
        Review this code which the scanner marked as {status}.
        Provide a brief bug report and then the fully optimized version.
        
        CODE:
        {payload.code}
        """

        # Step C: Routing to the chosen AI (require initialized clients)
        ai_text = ""
        if payload.model == "groq":
            if groq_client is None:
                raise HTTPException(status_code=503, detail="Groq client not available")
            chat_completion = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
            )
            ai_text = chat_completion.choices[0].message.content
        else:
            if gemini_client is None:
                raise HTTPException(status_code=503, detail="Gemini client not available")
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            ai_text = getattr(response, 'text', str(response))

        return {
            "security_score": status,
            "analysis": ai_text
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error during analysis: %s", e)
        return {"security_score": "error", "analysis": f"Backend Error: {str(e)}"}

# Start command
if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
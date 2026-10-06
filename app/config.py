"""All settings in one place, read from .env (so switching LLM = one line, no code change)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")          # ollama | groq | mock
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
TOP_K = int(os.getenv("TOP_K", "5"))

STORAGE = ROOT / "storage"                       # git-ignored: Chroma + SQLite live here
CHROMA_DIR = STORAGE / "chroma"
SQLITE_PATH = STORAGE / "university.sqlite"
DOCS_DIR = ROOT / "data" / "docs"
SOURCE_REGISTER = ROOT / "data" / "source_register.csv"

NOT_FOUND_MSG = "I could not find this information in the authorised university sources."

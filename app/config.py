"""All settings in one place, read from .env (so switching LLM = one line, no code change)."""
# WHAT THIS FILE IS: every setting the app needs, in one file. Other modules do "from app import config".
# An ENVIRONMENT VARIABLE is a named value set outside the code (in the shell, in Docker, or in a .env file).
# .env is a small text file of NAME=value lines that load_dotenv() reads at start. It is never committed (holds API keys).
# Real example: .env has "LLM_PROVIDER=groq" -> config.LLM_PROVIDER == "groq" -> llm.py calls Groq. No code change.
# If a variable is missing, the second argument of os.getenv() is the default (e.g. "ollama").
# os = read environment variables. Path = build file paths that work on Windows, Linux and inside Docker.
import os
from pathlib import Path

from dotenv import load_dotenv

# ROOT = the project folder (hcl_uc1/). __file__ is app/config.py, so parent.parent goes up two levels.
ROOT = Path(__file__).resolve().parent.parent
# Read hcl_uc1/.env into the environment. Variables already set (e.g. by docker-compose) are kept, not overwritten.
load_dotenv(ROOT / ".env")

# ---------- LLM and retrieval settings ----------
# LLM_PROVIDER picks the model service. OLLAMA_URL is where local Ollama listens (Docker overrides it to
# http://host.docker.internal:11434). OLLAMA_MODEL / GROQ_MODEL name the exact model.
# EMBED_MODEL = the small model (MiniLM) that turns text into number vectors for ChromaDB search.
# TOP_K = how many document chunks one search returns (5). int() because environment variables are always text.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")          # ollama | groq | mock
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
TOP_K = int(os.getenv("TOP_K", "5"))

# ---------- file locations ----------
# storage/ holds what the app builds (ChromaDB vectors + the SQLite database). data/ holds the inputs:
# data/docs/ = university documents, data/source_register.csv = the Annex B metadata for each document.
# In Docker both folders are mounted as volumes, so they survive container restarts.
STORAGE = ROOT / "storage"                       # git-ignored: Chroma + SQLite live here
CHROMA_DIR = STORAGE / "chroma"
SQLITE_PATH = STORAGE / "university.sqlite"
DOCS_DIR = ROOT / "data" / "docs"
SOURCE_REGISTER = ROOT / "data" / "source_register.csv"

# The exact sentence used whenever the answer is not in the sources (answer_type "not_found").
# One constant, so /ask, the graph and the UI all show the same wording.
NOT_FOUND_MSG = "I could not find this information in the authorised university sources."

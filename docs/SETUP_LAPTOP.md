# Laptop setup (each teammate, ~15 min)

## 1. Code
```powershell
git clone <repo-url>
cd <repo>
pip install -r requirements.txt
copy .env.example .env        # then put YOUR OWN Groq key in .env (never commit it)
python -m app.db              # creates storage/university.sqlite
python -m scripts.smoke       # must print health ok + ask 200
```

## 2. Local LLM (Ollama) — gaming laptops (RTX GPU) run it 5-10x faster than the thin laptop
```powershell
winget install Ollama.Ollama          # or download from ollama.com
ollama pull qwen2.5:7b-instruct       # 4.7 GB, named in the HCL guide
ollama run qwen2.5:7b-instruct "say OK"
ollama ps                             # PROCESSOR column should say "100% GPU"
python -m scripts.bench_llm qwen2.5:7b-instruct
```
Then in `.env`: `OLLAMA_MODEL=qwen2.5:7b-instruct`.
Paste the bench_llm summary line in the team chat — README "model choice" uses these numbers.

## 3. Which laptop runs the demo
The judges test live for 10 minutes, so the demo/server laptop = the fastest GPU laptop
(Acer Predator Helios Neo 16 or HP Omen 16), plugged into power, other apps closed.

Optional (only if the Wi-Fi allows laptop-to-laptop traffic): share one GPU Ollama with the team.
On the GPU laptop: `setx OLLAMA_HOST 0.0.0.0` → restart Ollama → find its IP with `ipconfig`.
On others: `.env` → `OLLAMA_URL=http://<that-ip>:11434`, test with `curl http://<that-ip>:11434/api/tags`.
College Wi-Fi often blocks this; if curl fails, everyone uses their own Ollama or `LLM_PROVIDER=mock` while coding.

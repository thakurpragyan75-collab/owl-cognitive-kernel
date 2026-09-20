# Model download (optional)

Weights do **not** belong in git.

Qwen3-Coder (Apache-2.0):

```
huggingface-cli download Qwen/Qwen3-Coder-30B-A3B-Instruct --local-dir ../models/qwen3-coder
```

Devstral Small 2507 (Apache-2.0). Official note: ~94GB BF16, Mac 32GB / RTX 4090 — **not 8GB**:

```
huggingface-cli download mistralai/Devstral-Small-2507 --local-dir ../models/devstral-small-2507
```

Then serve **one** of them with llama.cpp / vLLM and set the OpenAI base URL in `config/models.yaml`. Keep `max_loaded: 1`.

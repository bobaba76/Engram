from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Iterable

torch = None
torch_functional = None
AutoModel = None
AutoTokenizer = None


@lru_cache(maxsize=1)
def _load_embedding_dependencies() -> bool:
    global torch, torch_functional, AutoModel, AutoTokenizer
    try:
        import torch as torch_module
        import torch.nn.functional as torch_functional_module
        from transformers import AutoModel as auto_model_class, AutoTokenizer as auto_tokenizer_class
    except ImportError:
        return False
    torch = torch_module
    torch_functional = torch_functional_module
    AutoModel = auto_model_class
    AutoTokenizer = auto_tokenizer_class
    return True


def _fallback_embedding(text: str, dimensions: int = 32) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < dimensions:
        for byte in digest:
            values.append(byte / 255.0)
            if len(values) == dimensions:
                break
        digest = hashlib.sha256(digest).digest()
    return values


def _mean_pooling(model_output, attention_mask):
    token_embeddings = model_output[0]
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    return torch.sum(token_embeddings * input_mask_expanded, dim=1) / torch.clamp(input_mask_expanded.sum(dim=1), min=1e-9)


def _resolve_device(requested_device: str) -> str:
    if torch is None:
        return "cpu"
    normalized = (requested_device or "cpu").strip().lower()
    if normalized == "auto":
        if torch.cuda.is_available():
            return "cuda"
        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is not None and mps_backend.is_available():
            return "mps"
        return "cpu"
    if normalized == "cuda" and torch.cuda.is_available():
        return "cuda"
    if normalized == "mps":
        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is not None and mps_backend.is_available():
            return "mps"
    return "cpu"


def get_embedding_runtime_info(model_name: str, requested_device: str) -> dict[str, object]:
    info: dict[str, object] = {
        "model_name": model_name,
        "requested_device": requested_device,
        "backend": "deterministic_fallback",
        "resolved_device": "cpu",
        "cuda_available": False,
        "torch_version": "",
        "torch_cuda_build": "",
        "dependencies_loaded": False,
        "reason": "embedding dependencies unavailable",
    }
    if not model_name.startswith("jinaai/"):
        info["reason"] = "model not handled by transformer embedder"
        return info
    if not _load_embedding_dependencies():
        return info
    info["dependencies_loaded"] = True
    if torch is not None:
        info["torch_version"] = str(getattr(torch, "__version__", ""))
        info["torch_cuda_build"] = str(getattr(torch.version, "cuda", "") or "")
        info["cuda_available"] = bool(torch.cuda.is_available())
    resolved_device = _resolve_device(requested_device)
    info["resolved_device"] = resolved_device
    tokenizer, model = _load_jina_model(model_name)
    if tokenizer is None or model is None or torch is None or torch_functional is None:
        info["reason"] = "transformer model load failed; using deterministic fallback"
        return info
    info["backend"] = "jina_transformers"
    if requested_device and requested_device.strip().lower() == "cuda" and not info["torch_cuda_build"]:
        info["reason"] = "PyTorch CPU-only build detected; install a CUDA-enabled torch build"
        return info
    if requested_device and requested_device.strip().lower() == "cuda" and not info["cuda_available"]:
        info["reason"] = "CUDA requested but unavailable to PyTorch at runtime"
        return info
    if requested_device and requested_device.strip().lower() != resolved_device:
        info["reason"] = f"requested {requested_device}, using {resolved_device}"
    else:
        info["reason"] = f"using {resolved_device}"
    return info


def embedding_backend_name(model_name: str) -> str:
    if model_name.startswith("jinaai/"):
        if not _load_embedding_dependencies():
            return "deterministic_fallback"
        tokenizer, model = _load_jina_model(model_name)
        if tokenizer is not None and model is not None and torch is not None and torch_functional is not None:
            return "jina_transformers"
    return "deterministic_fallback"


@lru_cache(maxsize=2)
def _load_jina_model(model_name: str):
    if not _load_embedding_dependencies():
        return None, None
    if AutoTokenizer is None or AutoModel is None or torch is None:
        return None, None
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        model = AutoModel.from_pretrained(model_name, trust_remote_code=True, attn_implementation="eager")
        model.eval()
        return tokenizer, model
    except Exception:
        return None, None


def embed_texts(
    texts: Iterable[str],
    model_name: str,
    batch_size: int = 24,
    max_length: int = 512,
    device: str = "cpu",
) -> list[list[float]]:
    text_list = list(texts)
    info = get_embedding_runtime_info(model_name, device)
    if model_name.startswith("jinaai/"):
        tokenizer, model = _load_jina_model(model_name)
        if tokenizer is not None and model is not None and torch is not None and torch_functional is not None:
            resolved_device = _resolve_device(device)
            model = model.to(resolved_device)
            embeddings_batches = []
            for start in range(0, len(text_list), batch_size):
                batch = text_list[start:start + batch_size]
                encoded_input = tokenizer(batch, padding=True, truncation=True, max_length=max_length, return_tensors="pt")
                encoded_input = {key: value.to(resolved_device) for key, value in encoded_input.items()}
                with torch.inference_mode():
                    model_output = model(**encoded_input)
                embeddings = _mean_pooling(model_output, encoded_input["attention_mask"])
                embeddings = torch_functional.normalize(embeddings, p=2, dim=1)
                embeddings_batches.extend(embeddings.cpu().tolist())
                del encoded_input
                del model_output
                del embeddings
                if resolved_device == "cuda":
                    torch.cuda.empty_cache()
            return embeddings_batches
    return [_fallback_embedding(text) for text in text_list]

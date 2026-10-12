"""Local NLI cross-encoder (cross-encoder/nli-deberta-v3-xsmall, Apache-2.0, ONNX).

Used for a judge-free faithfulness score: each answer statement is checked for
entailment against the cited contexts (max over sentence windows, as in SummaC-ZS). This mirrors
the RAGAS faithfulness idea (share of answer claims supported by the context) with a
small NLI model instead of an LLM judge, and is labelled as such in all reports.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache

import numpy as np

from app.config import get_settings

REPO = "cross-encoder/nli-deberta-v3-xsmall"


class NLI:
    def __init__(self) -> None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        cache = str(get_settings().model_cache_dir)
        mp = hf_hub_download(REPO, "onnx/model.onnx", cache_dir=cache)
        tp = hf_hub_download(REPO, "tokenizer.json", cache_dir=cache)
        cp = hf_hub_download(REPO, "config.json", cache_dir=cache)
        with open(cp) as fh:
            self.labels = {int(k): v for k, v in json.load(fh)["id2label"].items()}
        self.tok = Tokenizer.from_file(tp)
        self.tok.enable_truncation(512)
        self.sess = ort.InferenceSession(mp, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}
        self.name = f"local:{REPO}"
        self._lock = threading.Lock()

    def probs(self, premise: str, hypothesis: str) -> dict[str, float]:
        e = self.tok.encode(premise, hypothesis)
        feed = {"input_ids": np.array([e.ids], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask], dtype=np.int64)}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.array([e.type_ids], dtype=np.int64)
        with self._lock:
            logits = self.sess.run(None, feed)[0][0]
        p = np.exp(logits - logits.max())
        p = p / p.sum()
        return {self.labels[i]: float(x) for i, x in enumerate(p)}

    def entailment(self, contexts: list[str], statement: str) -> float:
        """Max entailment over sentence windows of the contexts (SummaC-ZS style, Laban et al. 2022).

        Small NLI models are trained on short premises; scoring 1-3 sentence windows avoids
        missing support that is buried in a long passage.
        """
        from app.services.ai.text import split_sentences

        best = 0.0
        for c in contexts:
            sents: list[str] = []
            for para in c.split("\n"):
                sents.extend(split_sentences(para) or [para])
            sents = [x for x in sents if x.strip()] or [c]
            windows = {" ".join(sents[i : i + w]) for w in (1, 2, 3) for i in range(len(sents))}
            for win in windows:
                best = max(best, self.probs(win, statement).get("entailment", 0.0))
                if best > 0.95:
                    return best
        return best


@lru_cache
def get_nli() -> NLI:
    return NLI()

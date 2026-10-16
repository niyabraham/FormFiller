"""OPTIONAL ablation: a WordNet-backed `semantic.TermProvider` (pip install wn==0.0.23, which bundles WordNet 3.0).

Not used by the shipped pipeline. `python tools/evaluate_semantic.py --split dev --provider wordnet` measures whether
shared-synset equivalence adds anything on top of the closed lexicon; the result is recorded in PROJECT_COMPLETION.md.
"""

from __future__ import annotations

from functools import lru_cache


class WordNetProvider:
    name = "wordnet"

    def __init__(self) -> None:
        from wn import WordNet

        self._wn = WordNet()

    @lru_cache(maxsize=4096)  # noqa: B019 - one provider instance per process
    def _syn(self, word: str) -> frozenset[str]:
        return frozenset(s.name() for s in self._wn.synsets(word, pos="n"))

    def similarity(self, question_term: str, leaf_term: str) -> float:
        a, b = self._syn(question_term), self._syn(leaf_term)
        return 0.8 if a and b and a & b else 0.0

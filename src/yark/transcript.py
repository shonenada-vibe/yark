"""Turn streaming ASR payloads into committed text ready to type."""

from __future__ import annotations

from dataclasses import dataclass, field

from yark.protocol import ServerResponse


def _needs_space(prev: str, nxt: str) -> bool:
    if not prev or not nxt:
        return False
    return prev[-1].isalnum() and nxt[0].isalnum()


@dataclass
class TranscriptCommitter:
    """Commit definite utterances once; flush leftovers on the last package.

    Uses (start_time, text) as the utterance identity so both `result_type=full`
    (all utterances replayed) and `result_type=single` (only the latest sentence)
    stay correct.
    """

    _seen: set[tuple[int, str]] = field(default_factory=set)
    _emitted: str = ""

    def feed(self, response: ServerResponse) -> list[str]:
        pieces: list[str] = []
        utterances = response.utterances()

        for utt in utterances:
            if not isinstance(utt, dict):
                continue
            text = str(utt.get("text") or "").strip()
            if not text:
                continue
            start = int(utt.get("start_time") or 0)
            definite = bool(utt.get("definite"))
            if definite:
                pieces.extend(self._commit(start, text))

        if response.is_last_package:
            leftovers = [
                utt
                for utt in utterances
                if isinstance(utt, dict)
                and not bool(utt.get("definite"))
                and str(utt.get("text") or "").strip()
            ]
            for utt in leftovers:
                text = str(utt.get("text") or "").strip()
                start = int(utt.get("start_time") or 0)
                pieces.extend(self._commit(start, text))
            if not pieces and not leftovers:
                full = response.text().strip()
                if full and full != self._emitted:
                    suffix = _suffix_after(self._emitted, full)
                    if suffix:
                        self._emitted = _join(self._emitted, suffix)
                        pieces.append(suffix)

        return pieces

    def _commit(self, start: int, text: str) -> list[str]:
        key = (start, text)
        if key in self._seen:
            return []
        self._seen.add(key)
        out = text
        if _needs_space(self._emitted, out):
            out = " " + out
        self._emitted = self._emitted + out
        return [out]


def _join(prev: str, nxt: str) -> str:
    if _needs_space(prev, nxt):
        return prev + " " + nxt
    return prev + nxt


def _suffix_after(committed: str, full: str) -> str:
    if not committed:
        return full
    if full.startswith(committed):
        return full[len(committed) :]
    # Best-effort: if committed is a prefix of full ignoring inserted spaces.
    stripped_committed = committed.replace(" ", "")
    stripped_full = full.replace(" ", "")
    if stripped_full.startswith(stripped_committed):
        return full[len(committed) :] if len(full) >= len(committed) else full
    return full

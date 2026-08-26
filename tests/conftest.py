# -*- coding: utf-8 -*-
"""
검증용 공용 도구.

여기서 가장 중요한 것은 **가짜 모델**이다.
Whisper·pyannote·임베딩 모델은 수 GB짜리라 검증 때마다 돌릴 수 없고,
망이 막힌 곳에서는 아예 받을 수도 없다. 그렇다고 그 경로를 검증 없이
두면, 정작 사용자 PC에서 처음 돌릴 때 터진다.

그래서 모델이 내놓는 것과 똑같은 모양의 가짜를 만들어 끼워 넣고,
**우리 코드**가 그것을 제대로 다루는지 본다. 모델 자체의 정확도는
우리가 검증할 대상이 아니다.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def use_temp_db(tmp_path):
    """검증마다 깨끗한 DB를 쓴다."""
    os.environ["EVIDENCE_DB"] = str(tmp_path / "t.db")
    os.environ["EVIDENCE_WORK"] = str(tmp_path / "work")
    for mod in list(sys.modules):
        if mod.startswith("evidence"):
            del sys.modules[mod]
    from evidence import config
    config._HW = None
    return config


# ─────────────────────────────────────────────────────────
# 가짜 Whisper
# ─────────────────────────────────────────────────────────
class FakeWord:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


class FakeSegment:
    """faster_whisper.Segment 와 같은 속성을 갖는다."""

    def __init__(self, start, end, text, *, avg_logprob=-0.3,
                 no_speech_prob=0.02, compression_ratio=1.4, words=True):
        self.start, self.end, self.text = start, end, text
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob
        self.compression_ratio = compression_ratio
        if words:
            parts = text.split() or [text]
            step = (end - start) / max(len(parts), 1)
            self.words = [
                FakeWord(w, round(start + i * step, 3),
                         round(start + (i + 1) * step, 3))
                for i, w in enumerate(parts)
            ]
        else:
            self.words = None


class FakeInfo:
    def __init__(self, duration):
        self.duration = duration
        self.language = "ko"


class FakeWhisper:
    """
    model.transcribe(path, **opts) 를 흉내낸다.
    받은 옵션을 기록해 두어, 우리가 의도한 설정이 실제로 전달되는지 본다.
    """

    def __init__(self, segments, duration=60.0, reject_hotwords=False):
        self._segments = segments
        self._duration = duration
        self.reject_hotwords = reject_hotwords
        self.calls = []

    def transcribe(self, path, **opts):
        if self.reject_hotwords and "hotwords" in opts:
            # 구버전 faster-whisper 흉내: hotwords를 모르면 TypeError
            raise TypeError("transcribe() got an unexpected keyword 'hotwords'")
        self.calls.append({"path": str(path), "opts": dict(opts)})
        return iter(self._segments), FakeInfo(self._duration)


def install_fake_whisper(audio_module, model_name, fake):
    audio_module._models[model_name] = fake
    return fake


# ─────────────────────────────────────────────────────────
# 가짜 임베딩
# ─────────────────────────────────────────────────────────
class FakeEmbedder:
    """
    글자 단위 특징으로 벡터를 만든다.
    의미를 아는 것은 아니지만, 비슷한 문장이 비슷한 벡터를 갖게 되어
    RRF 융합과 벡터 검색 배관을 검증하기에 충분하다.
    """

    def __init__(self, dim=1024):
        self.dim = dim

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        import math
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for i, ch in enumerate(str(t)):
                v[(ord(ch) * 7 + i) % self.dim] += 1.0
            if normalize_embeddings:
                n = math.sqrt(sum(x * x for x in v)) or 1.0
                v = [x / n for x in v]
            out.append(v)
        return out


def install_fake_embedder(embed_module, dim=1024):
    embed_module._model = FakeEmbedder(dim)
    embed_module._load_failed = False
    return embed_module._model


# ─────────────────────────────────────────────────────────
# 가짜 화자 분리
# ─────────────────────────────────────────────────────────
def fake_turns(pairs):
    """[(시작, 끝, '화자')] → diarize가 기대하는 모양"""
    return [{"start": s, "end": e, "speaker": sp} for s, e, sp in pairs]


# ─────────────────────────────────────────────────────────
# 검증 도우미
# ─────────────────────────────────────────────────────────
class Check:
    def __init__(self, title):
        self.title = title
        self.passed = []
        self.failed = []

    def ok(self, cond, label, detail=""):
        if cond:
            self.passed.append(label)
        else:
            self.failed.append((label, detail))
        return cond

    def eq(self, got, want, label):
        return self.ok(got == want, label, f"기대 {want!r} / 실제 {got!r}")

    def report(self) -> bool:
        from evidence.console import marks
        m = marks()
        mark = m["ok"] if not self.failed else m["no"]
        print(f"\n{mark} {self.title} - 통과 {len(self.passed)} / 실패 {len(self.failed)}")
        for label, detail in self.failed:
            print(f"     {m['no']} {label}")
            if detail:
                print(f"        {detail}")
        return not self.failed

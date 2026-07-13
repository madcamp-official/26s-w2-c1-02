#!/usr/bin/env python
"""페르소나 레퍼런스 생성 — Path C (VoxCPM2 셀프 캐스팅 + 미세 보정).

실측 발견(2026-07-13): VoxCPM2의 `default` voice는 고정 화자가 아니라 **요청마다
화자를 샘플링**한다(base 5종 F0 117~299Hz). 구 캐리커처 라우트의 방향 랜덤성은
librosa 변형 문제 이전에 베이스 화자가 복불복이었던 것.

전략: 페르소나 대본을 default로 N회 합성 → F0를 실측해 **목표 대역에 드는 샘플을
선발**(= VoxCPM2 본연의 자연스러운 음색을 그대로 레퍼런스로) → 대역을 못 맞춘
페르소나만 parselmouth(Praat change gender)로 포먼트+피치 **정합** 미세 보정
(edge-tts 실측에서 정합 변형은 클로닝을 통과함이 확인됨 — 2d 결과).
변형 비율은 캡(0.85~1.2)을 걸어 아티팩트를 억제한다.

의존성: pip install praat-parselmouth numpy
실행:   TTS_URL=http://127.0.0.1:18100 python build_persona_refs_voxcpm.py   # 터널 경유
        python build_persona_refs_voxcpm.py kkondae jammin                    # 일부만
산출:   voices/refs_vox/{persona}.wav (+ candidates_vox/에 전체 샘플 보존)
이후:   청취 검수 → refs/ 교체 → 프로파일 재계산 → 재기동 (persona_voices.md (3)단계)
"""

from __future__ import annotations

import array
import json
import os
import sys
import urllib.request
import wave
from pathlib import Path

import numpy as np
import parselmouth
from parselmouth.praat import call as praat_call

from build_persona_refs_edge import SCRIPTS, _normalize_peak
from eval_persona_voices import TARGETS

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "voices" / "refs_vox"
CAND_DIR = OUT_DIR / "candidates_vox"
TTS_URL = os.environ.get("TTS_URL", "http://127.0.0.1:8100")
N_SAMPLES = 6
# persona → 목표 F0 중심. 선발 우선, 보정은 중심으로 끌어당길 때만.
F0_CENTER = {"egen": 215.0, "teto": 118.0, "kkondae": 100.0, "mungcheong": 150.0, "jammin": 270.0}
# persona → (포먼트 비율, 피치범위 비율, 길이 비율) — 보정이 필요할 때만 적용
CORRECTION_STYLE = {
    "egen": (1.06, 1.10, 1.00),
    "teto": (0.96, 1.00, 0.97),
    "kkondae": (0.90, 0.90, 1.08),
    "mungcheong": (1.00, 1.05, 1.05),
    "jammin": (1.12, 1.15, 0.94),
}
PITCH_RATIO_CAP = (0.80, 1.25)  # 이 이상 당기면 아티팩트 — 캡 밖이면 가장 가까운 샘플 유지


def _synth_default(text: str) -> bytes:
    payload = json.dumps({
        "model": "openbmb/VoxCPM2", "input": text,
        "voice": "default", "response_format": "wav",
    }).encode()
    req = urllib.request.Request(
        f"{TTS_URL}/v1/audio/speech", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    if not data.startswith(b"RIFF"):
        raise RuntimeError(f"응답이 wav 아님: {data[:60]!r}")
    return data


def _f0_median(path: Path) -> float:
    snd = parselmouth.Sound(str(path))
    freqs = snd.to_pitch(time_step=0.01, pitch_floor=60.0, pitch_ceiling=500.0)
    voiced = freqs.selected_array["frequency"]
    voiced = voiced[voiced > 0]
    return float(np.median(voiced)) if voiced.size else 0.0


def _save_normalized(snd: parselmouth.Sound, dst: Path) -> None:
    """Sound → 48kHz mono PCM16 + 피크 정규화 (refs 관례)."""
    if snd.sampling_frequency != 48000:
        snd = snd.resample(48000)
    pcm = (np.clip(snd.values[0], -1.0, 1.0) * 32767).astype("<i2").tobytes()
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(_normalize_peak(pcm))


def build(persona: str) -> None:
    script = SCRIPTS[persona]
    lo, hi = TARGETS[persona][0]
    center = F0_CENTER[persona]
    CAND_DIR.mkdir(parents=True, exist_ok=True)

    samples: list[tuple[Path, float]] = []
    for i in range(N_SAMPLES):
        p = CAND_DIR / f"{persona}__s{i}.wav"
        p.write_bytes(_synth_default(script))
        f0 = _f0_median(p)
        samples.append((p, f0))
        print(f"  [{persona} s{i}] F0 {f0:.0f}Hz {'✓대역내' if lo <= f0 <= hi else ''}")

    in_band = [(p, f0) for p, f0 in samples if lo <= f0 <= hi]
    if in_band:
        best, f0 = min(in_band, key=lambda x: abs(np.log2(x[1] / center)))
        snd = parselmouth.Sound(str(best))
        print(f"  → 선발: {best.name} ({f0:.0f}Hz, 무보정)")
    else:
        best, f0 = min(samples, key=lambda x: abs(np.log2(x[1] / center)))
        ratio = float(np.clip(center / f0, *PITCH_RATIO_CAP))
        fmt, rng, dur = CORRECTION_STYLE[persona]
        snd = parselmouth.Sound(str(best))
        snd = praat_call(snd, "Change gender", 75, 600, fmt, f0 * ratio, rng, dur)
        print(f"  → 보정: {best.name} ({f0:.0f}Hz → x{ratio:.2f} ≈ {f0 * ratio:.0f}Hz, 포먼트 x{fmt})")

    dst = OUT_DIR / f"{persona}.wav"
    _save_normalized(snd, dst)
    print(f"  → {dst.relative_to(HERE)} (최종 F0 {_f0_median(dst):.0f}Hz)")


def main() -> None:
    personas = sys.argv[1:] or list(SCRIPTS)
    if unknown := set(personas) - set(SCRIPTS):
        sys.exit(f"알 수 없는 페르소나: {sorted(unknown)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in personas:
        print(f"[{p}] 대역 {TARGETS[p][0]} / 중심 {F0_CENTER[p]}Hz — {N_SAMPLES}회 샘플링")
        build(p)
    print("\n다음: eval_persona_voices.py voices/refs_vox --distances → 청취 검수 → refs/ 교체")


if __name__ == "__main__":
    main()

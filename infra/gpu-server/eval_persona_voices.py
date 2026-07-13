#!/usr/bin/env python
"""페르소나 음성 자동 채점 하네스 — 레퍼런스 후보/합성 출력 공용.

지금까지 "상태가 좋다/나쁘다"가 청취 소감이었던 것을 수치화한다. 레퍼런스 후보
(refs_edge/candidates)와 클로닝 후 합성 출력(방향 검증) 양쪽에 같은 잣대를 쓴다.

지표
- duration / 침묵 비율 / 클리핑: refs_moss 류의 truncation·생성 불안정 검출
- median F0 (+p10–p90): 페르소나 방향(꼰대 최저 … 잼민 최고) — TARGETS 대역과 비교
- 발화 속도(음절/초, 대본 기준): 페르소나 페이스(꼰대 느림, 테토/잼민 빠름)
- --stt-url: STT 서버 왕복 CER(명료도) — GPU 서버가 있어야 함 (2단계)
- --distances: 파일 간 MFCC 평균벡터 거리 행렬 — 5종 구별성·화자 중복 검출

사용
  python eval_persona_voices.py voices/refs_edge/candidates            # 로컬 지표
  python eval_persona_voices.py voices/refs_edge --distances           # 최종 5종 비교
  python eval_persona_voices.py voices/refs_edge --stt-url http://<gpu>:8200   # +CER

파일명 규약: {persona}.wav 또는 {persona}__{tag}.wav → 페르소나를 파일명에서 추론.
의존성: pip install praat-parselmouth numpy  (+CER은 서버만 있으면 stdlib)
TARGETS 대역은 휴리스틱 초깃값 — 청취 검수와 함께 조정한다.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

import numpy as np
import parselmouth

from build_persona_refs_edge import SCRIPTS

# persona → (F0 대역 Hz, 발화속도 대역 음절/초). 방향 서열이 핵심:
# kkondae < teto < mungcheong < egen < jammin (F0), kkondae·mungcheong 느림.
TARGETS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "egen": ((170.0, 260.0), (3.5, 5.5)),
    "teto": ((95.0, 140.0), (4.5, 6.5)),
    "kkondae": ((75.0, 130.0), (2.8, 4.5)),
    "mungcheong": ((100.0, 220.0), (2.5, 4.5)),
    "jammin": ((210.0, 330.0), (4.5, 7.0)),
}
DURATION_BAND = (8.0, 22.0)  # VoxCPM2 레퍼런스 권장 10~20s + 여유
SILENCE_DB_DROP = 25.0  # 최대 강도 대비 -25dB 미만 프레임 = 침묵


def _persona_of(path: Path) -> str | None:
    stem = path.stem.split("__")[0]
    return stem if stem in SCRIPTS else None


def _hangul_syllables(text: str) -> int:
    return sum(1 for c in text if "가" <= c <= "힣")


def _norm_for_cer(text: str) -> str:
    """표기 정규화: 한글·숫자·라틴만 남김(공백/구두점 제거) — stt-client-workflow의
    CER 계산 관례(표기 정규화 제외)와 동일 취지."""
    text = unicodedata.normalize("NFC", text)
    return "".join(c for c in text if c.isalnum())


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def analyze(path: Path) -> dict:
    snd = parselmouth.Sound(str(path))
    dur = snd.get_total_duration()

    pitch = snd.to_pitch(time_step=0.01, pitch_floor=60.0, pitch_ceiling=500.0)
    freqs = pitch.selected_array["frequency"]
    voiced = freqs[freqs > 0]
    f0_med = float(np.median(voiced)) if voiced.size else 0.0
    f0_p10, f0_p90 = (
        (float(np.percentile(voiced, 10)), float(np.percentile(voiced, 90)))
        if voiced.size
        else (0.0, 0.0)
    )

    intensity = snd.to_intensity(time_step=0.01)
    vals = intensity.values[0]
    silence_ratio = float(np.mean(vals < (vals.max() - SILENCE_DB_DROP)))

    samples = snd.values[0]
    clip_ratio = float(np.mean(np.abs(samples) > 0.985))

    row = {
        "duration_sec": round(dur, 1),
        "f0_median_hz": round(f0_med),
        "f0_p10_p90": (round(f0_p10), round(f0_p90)),
        "silence_pct": round(silence_ratio * 100),
        "clip_pct": round(clip_ratio * 100, 2),
    }

    if persona := _persona_of(path):
        # 월클록 기준 발화 속도(쉼 포함) — 페르소나 페이스는 "쉼까지 포함한 체감
        # 속도"라서 침묵 제외 시간으로 나누면 과대 계산된다(1차 실측에서 확인).
        syl_rate = _hangul_syllables(SCRIPTS[persona]) / (dur or 1.0)
        (f0_lo, f0_hi), (r_lo, r_hi) = TARGETS[persona]
        flags = []
        if not (DURATION_BAND[0] <= dur <= DURATION_BAND[1]):
            flags.append("duration")
        if not (f0_lo <= f0_med <= f0_hi):
            flags.append("f0")
        if not (r_lo <= syl_rate <= r_hi):
            flags.append("tempo")
        if clip_ratio > 0.001:
            flags.append("clip")
        row |= {
            "persona": persona,
            "syl_per_sec": round(syl_rate, 1),
            "flags": flags,
        }
    return row


def transcribe_cer(path: Path, ref_text: str, stt_url: str) -> float:
    """STT 왕복 CER (0.0=완벽). stdlib만 사용 — GPU 서버 /transcribe 호출.

    ref_text: 이 오디오가 말했어야 하는 원문 — 레퍼런스는 SCRIPTS, 합성 출력은
    합성에 넣은 질문 텍스트를 넘긴다.
    """
    import mimetypes
    import urllib.request
    import uuid

    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "audio/wav"
    parts = b""
    for name, value in (("language", "Korean"), ("timestamps", "false")):
        parts += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
        ).encode()
    parts += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{path.name}\"\r\nContent-Type: {ctype}\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{stt_url.rstrip('/')}/transcribe",
        data=parts,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        text = json.loads(resp.read())["text"]
    ref, hyp = _norm_for_cer(ref_text), _norm_for_cer(text)
    return _levenshtein(ref, hyp) / max(len(ref), 1)


def mfcc_mean(path: Path) -> np.ndarray:
    mfcc = parselmouth.Sound(str(path)).to_mfcc(number_of_coefficients=12)
    return mfcc.to_array()[1:].mean(axis=1)  # c0(에너지) 제외


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="wav 파일 또는 디렉터리")
    ap.add_argument("--stt-url", help="STT 서버 URL (예: http://<gpu>:8200) — CER 채점")
    ap.add_argument("--distances", action="store_true", help="MFCC 거리 행렬 출력")
    ap.add_argument("--json-out", help="결과를 JSON으로도 저장")
    args = ap.parse_args()

    target = Path(args.target)
    files = sorted(target.glob("*.wav")) if target.is_dir() else [target]
    if not files:
        sys.exit(f"wav 없음: {target}")

    results: dict[str, dict] = {}
    for f in files:
        row = analyze(f)
        if args.stt_url and (persona := row.get("persona")):
            try:
                row["cer_pct"] = round(
                    transcribe_cer(f, SCRIPTS[persona], args.stt_url) * 100, 1
                )
            except Exception as e:  # noqa: BLE001 — 채점은 계속
                row["cer_pct"] = f"오류: {e}"
        results[f.name] = row
        flags = ",".join(row.get("flags", [])) or "OK"
        cer = f" cer={row['cer_pct']}%" if "cer_pct" in row else ""
        print(
            f"{f.name:32s} {row['duration_sec']:5.1f}s  F0 {row['f0_median_hz']:3d}Hz "
            f"({row['f0_p10_p90'][0]}–{row['f0_p10_p90'][1]})  "
            f"{row.get('syl_per_sec', '-'):>4}syl/s  침묵{row['silence_pct']:3d}%{cer}  [{flags}]"
        )

    if args.distances and len(files) > 1:
        vecs = {f.name: mfcc_mean(f) for f in files}
        names = list(vecs)
        print("\nMFCC 거리 행렬 (낮음 = 비슷한 화자 — 최종 5종은 전부 서로 멀어야 함)")
        print(" " * 26 + "  ".join(n[:10].rjust(10) for n in names))
        for a in names:
            row = "  ".join(
                f"{float(np.linalg.norm(vecs[a] - vecs[b])):10.1f}" for b in names
            )
            print(f"{a[:24].ljust(24)}  {row}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str)
        )
        print(f"\nJSON 저장: {args.json_out}")


if __name__ == "__main__":
    main()

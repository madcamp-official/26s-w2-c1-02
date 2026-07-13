#!/usr/bin/env python
"""페르소나 레퍼런스 wav 생성 — Path B-2 (로컬 MOSS-VoiceGenerator 부트스트랩).

Gemini TTS 라우트(Path B-1)가 키 정책으로 막혔을 때의 **완전 로컬·무료** 대안.
MOSS-VoiceGenerator(1.7B)는 zero-shot voice design 모델 — 레퍼런스 오디오 없이
`instructions`(자연어 음성 묘사)만으로 새 목소리를 만든다. vllm-omni가 이미
지원한다(deploy/moss_voice_generator.yaml, /v1/audio/speech의 instructions 필드).

전제: 부트스트랩 서버가 8101에 떠 있어야 한다 — bootstrap_persona_refs_moss.sh가
서버 기동/종료까지 오케스트레이션한다(3090 24GB 특성상 기존 TTS/STT 서버를
잠시 내려야 함). 이 스크립트는 생성만 담당.

산출: voices/refs_moss/{persona}.wav — 검수 후 교체는 Path B와 동일:
  cp voices/refs_moss/*.wav voices/refs/ → 프로파일 (3)단계 재계산 → start_tts.sh 재기동

실행: python3 build_persona_refs_moss.py   (표준 라이브러리만 사용)
"""

from __future__ import annotations

import array
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "voices" / "refs_moss"
BASE_URL = os.environ.get("MOSS_TTS_URL", "http://127.0.0.1:8101")
MODEL = "OpenMOSS-Team/MOSS-VoiceGenerator"
MAX_RETRIES = 2
TIMEOUT = 300  # 첫 요청은 워밍업 포함이라 여유 있게

# ── 페르소나별 음성 묘사(voice design instructions) + 대사 ────────────────────
# 묘사는 배우 지시가 아니라 **목소리 자체의 스펙**으로 쓴다(모델 계약).
# 대사는 build_persona_voices.sh / build_persona_refs_gemini.py 확정본과 동일.
PERSONAS: list[tuple[str, str, str]] = [
    (
        "egen",
        "20대 후반 여성의 부드럽고 따뜻한 중고음. 미소를 머금은 배려하는 말투, "
        "느긋한 속도, 문장 끝을 살짝 올리는 공감형 억양. 공격성이 전혀 없는 다정한 목소리.",
        "아, 발표 정말 잘 들었어요. 준비 많이 하신 게 느껴져서 좋았어요. 다만 이 부분이 "
        "조금 더 궁금했는데요, 이렇게 생각하신 이유를 편하게 말씀해 주실 수 있을까요?",
    ),
    (
        "teto",
        "30대 남성의 낮고 단단한 중저음. 빠르고 또렷한 발화, 군더더기 없는 단정적 억양. "
        "감정 과장 없이 차갑고 직설적으로 몰아붙이는 실무 리더의 목소리.",
        "핵심만 짚죠. 방금 그 수치, 근거가 뭡니까? 결론이 먼저고 이유는 그다음이에요. "
        "지금 설명으로는 설득이 안 됩니다. 다시 정리해서 말해 보세요.",
    ),
    (
        "kkondae",
        "50대 후반 남성의 굵고 걸걸한 저음. 느리고 사이사이 뜸을 들이는 훈계조, "
        "거들먹거리며 가르치려 드는 억양, 문장 끝을 내리누르는 권위적인 목소리.",
        "어허, 내가 이 바닥 삼십 년인데 말이야. 요즘 친구들은 기본기가 없어. 그 정도 "
        "자료로 발표가 되나? 내가 젊었을 땐 이런 건 밤새서라도 다 외웠어. 자네, 이거 다시 해 와.",
    ),
    (
        "mungcheong",
        "20대의 다소 높고 물렁한 톤. 확신 없이 느리게 머뭇거리는 발화, 간투사가 많고 "
        "문장 끝을 자신 없게 흐리는 어리숙한 목소리.",
        "어, 그러니까, 음, 제가 잘 이해를 못 했는데요, 이게 그 앞에 말한 거랑 같은 "
        "건가요? 아 잠깐, 질문이 뭐였지, 아무튼 그거 좀 더 쉽게 설명해 주실 수 있어요?",
    ),
    (
        "jammin",
        "10~12세 남자아이의 높고 앳된 목소리. 빠르고 촐랑거리는 발화, 건방지고 놀리듯 "
        "까불거리는 억양, 말끝마다 힘을 주며 지기 싫어하는 초등학생 말투.",
        "에이 그거 저도 알아요. 그거 완전 기본 아님? 근데 발표자님 그거 틀린 거 같은데요? "
        "제 말이 맞잖아요. 기분 나쁘셨다면 죄송하구요.",
    ),
]


def _normalize(pcm: bytes) -> bytes:
    """피크 0.97 정규화(기존 refs 관례). 증폭 상한 4배."""
    samples = array.array("h")
    samples.frombytes(pcm)
    peak = max((abs(s) for s in samples), default=0) or 1
    scale = min(int(32767 * 0.97) / peak, 4.0)
    return array.array(
        "h", (max(-32768, min(32767, round(s * scale))) for s in samples)
    ).tobytes()


def _synthesize(instructions: str, text: str) -> bytes:
    payload = json.dumps({
        "model": MODEL,
        "input": text,
        "instructions": instructions,
        "response_format": "wav",
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/v1/audio/speech",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    last: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        if attempt:
            time.sleep(5 * attempt)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read()
            if not data.startswith(b"RIFF"):
                raise ValueError(f"응답이 wav가 아님: {data[:80]!r}")
            return data
        except (urllib.error.URLError, ValueError, OSError) as e:
            last = e
    raise RuntimeError(f"합성 실패({1 + MAX_RETRIES}회): {last}") from last


def _rewrap_normalized(wav_bytes: bytes, out_path: Path) -> float:
    """서버 wav를 열어 피크 정규화 후 저장. 재생 길이(초)를 반환."""
    import io

    with wave.open(io.BytesIO(wav_bytes), "rb") as r:
        params = r.getparams()
        frames = r.readframes(r.getnframes())
    if params.sampwidth != 2:
        raise RuntimeError(f"PCM16이 아님(sampwidth={params.sampwidth})")
    with wave.open(str(out_path), "wb") as w:
        w.setparams(params)
        w.writeframes(_normalize(frames))
    return params.nframes / params.framerate


def main() -> None:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/v1/audio/voices", timeout=10) as r:
            r.read()
    except (urllib.error.URLError, OSError):
        sys.exit(
            f"부트스트랩 서버({BASE_URL}) 응답 없음 — bash bootstrap_persona_refs_moss.sh 로 실행하세요."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, instructions, script in PERSONAS:
        wav = _synthesize(instructions, script)
        dur = _rewrap_normalized(wav, OUT_DIR / f"{name}.wav")
        print(f"[{name}] {dur:.1f}s -> {(OUT_DIR / (name + '.wav')).relative_to(HERE)}")

    print("\n청취 검수 후: cp voices/refs_moss/*.wav voices/refs/ → 프로파일 (3)단계 재계산 → 재기동")


if __name__ == "__main__":
    main()

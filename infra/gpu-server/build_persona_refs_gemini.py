#!/usr/bin/env python
"""페르소나 레퍼런스 wav 생성 — Path B (Gemini TTS 부트스트랩).

현재 voices/refs/는 캐리커처(default 합성 + 피치/템포 변형)라 5종 모두 같은
인공 음색의 변형이다. 이 스크립트는 지시(instruction)를 따르는 Gemini TTS로
**서로 다른 5개 기본 음색**에 페르소나 연기 지시문을 주어 레퍼런스를 새로
생성한다 — VoxCPM2가 클로닝할 원본의 사실감을 올리는 것이 목적.
(설계·연기 지시문 표: persona_voices.md "Path B" 절)

산출: voices/refs_gemini/{persona}.wav  (24kHz mono PCM16, 피크 정규화)
      — 작동 중인 voices/refs/를 덮지 않는다. 청취 검수 후 교체:

  cp voices/refs_gemini/*.wav voices/refs/         # 교체
  bash build_persona_voices.sh                     # (1)(2)는 건너뛰고 (3)만 돌려도 됨:
  #   또는 페르소나별로: CUDA_VISIBLE_DEVICES= python vllm-omni/examples/online_serving/\
  #     text_to_speech/voxcpm2/precompute_custom_voice.py --model openbmb/VoxCPM2 \
  #     --output-dir voices/profiles --voice-name egen --ref-audio voices/refs/egen.wav \
  #     --mode reference --device cpu
  # start_tts.sh 재기동으로 반영. voice 이름 불변 → 백엔드 수정 0.

실행 (google-genai가 있는 backend venv 사용, repo 루트 기준):
  backend/.venv/bin/python infra/gpu-server/build_persona_refs_gemini.py

키: $GEMINI_API_KEY 또는 backend/.env의 GEMINI_API_KEY.
"""

from __future__ import annotations

import array
import os
import sys
import time
import wave
from pathlib import Path

from google import genai
from google.genai import types

HERE = Path(__file__).resolve().parent          # infra/gpu-server/
OUT_DIR = HERE / "voices" / "refs_gemini"
TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
MAX_RETRIES = 2  # 429/일시 오류 대비

# ── 페르소나별 음성 사양 (Path B) ─────────────────────────────────────────────
# (base_voice, 연기 지시문, 대사) — 대사는 build_persona_voices.sh의 확정본과 동일.
# base_voice는 Gemini TTS 프리빌트 30종 중 페르소나 목표 음색(persona_voices.md
# 설계표)에 가장 가까운 것을 서로 다르게 배정 — 5종이 같은 음색의 변형이 되지
# 않게 하는 것이 Path B의 핵심.
PERSONAS: list[tuple[str, str, str, str]] = [
    (
        "egen",
        "Sulafat",  # Warm — 따뜻한 중고음
        "당신은 발표를 막 들은 20대 후반의 다정한 청중입니다. 부드럽고 따뜻한 목소리로, "
        "미소를 머금은 채 상대를 배려하듯 느긋하게 말하세요. 문장 끝은 살짝 올려 "
        "공감하는 느낌을 주고, 공격성은 전혀 없이:",
        "아, 발표 정말 잘 들었어요. 준비 많이 하신 게 느껴져서 좋았어요. 다만 이 부분이 "
        "조금 더 궁금했는데요, 이렇게 생각하신 이유를 편하게 말씀해 주실 수 있을까요?",
    ),
    (
        "teto",
        "Alnilam",  # Firm — 단단한 중저음
        "당신은 회의실에서 발표를 검증하는 30대 실무 리더입니다. 낮고 단단한 목소리로, "
        "군더더기 없이 빠르고 또렷하게, 단정적인 억양으로 몰아붙이듯 말하세요. "
        "감정 과장 없이 차갑고 직설적으로:",
        "핵심만 짚죠. 방금 그 수치, 근거가 뭡니까? 결론이 먼저고 이유는 그다음이에요. "
        "지금 설명으로는 설득이 안 됩니다. 다시 정리해서 말해 보세요.",
    ),
    (
        "kkondae",
        "Algenib",  # Gravelly — 걸걸한 저음
        "당신은 후배들을 가르치려 드는 50대 후반 남성 상사입니다. 낮고 굵은 목소리로 "
        "느리게, 사이사이 뜸을 들이며 거들먹거리는 훈계조로 말하세요. '어허' 하고 "
        "혀를 차듯 시작하고, 문장 끝은 내리누르며 단정하듯이:",
        "어허, 내가 이 바닥 삼십 년인데 말이야. 요즘 친구들은 기본기가 없어. 그 정도 "
        "자료로 발표가 되나? 내가 젊었을 땐 이런 건 밤새서라도 다 외웠어. 자네, 이거 다시 해 와.",
    ),
    (
        "mungcheong",
        "Umbriel",  # Easy-going — 물렁하고 느긋한 톤
        "당신은 발표 내용을 절반쯤 놓친 20대 청중입니다. 다소 높고 물렁한 목소리로, "
        "확신 없이 느리게 머뭇거리며 말하세요. '어…', '음…' 같은 간투사를 그대로 살리고, "
        "문장 끝은 자신 없게 흐리면서:",
        "어, 그러니까, 음, 제가 잘 이해를 못 했는데요, 이게 그 앞에 말한 거랑 같은 "
        "건가요? 아 잠깐, 질문이 뭐였지, 아무튼 그거 좀 더 쉽게 설명해 주실 수 있어요?",
    ),
    (
        "jammin",
        "Leda",  # Youthful — 높고 앳된 톤
        "당신은 아는 척하기 좋아하는 초등학생 남자아이입니다. 높고 앳된 목소리로 빠르게, "
        "촐랑거리며 건방진 말투로 말하세요. 말끝마다 힘을 주고 놀리듯 까불거리며, "
        "지기 싫어하는 어조로:",
        "에이 그거 저도 알아요. 그거 완전 기본 아님? 근데 발표자님 그거 틀린 거 같은데요? "
        "제 말이 맞잖아요. 기분 나쁘셨다면 죄송하구요.",
    ),
]


def _api_key() -> str:
    if key := os.environ.get("GEMINI_API_KEY"):
        return key
    env = HERE.parent.parent / "backend" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    sys.exit("GEMINI_API_KEY 없음 — 환경변수 또는 backend/.env에 설정하세요.")


def _pcm_rate(mime_type: str) -> int:
    # 예: "audio/L16;codec=pcm;rate=24000"
    for part in (mime_type or "").split(";"):
        if part.strip().startswith("rate="):
            return int(part.split("=", 1)[1])
    return 24000


def _normalize(pcm: bytes) -> bytes:
    """피크 0.97 정규화 (build_persona_voices.sh와 동일 관례). 증폭은 4배 상한."""
    samples = array.array("h")
    samples.frombytes(pcm)
    peak = max((abs(s) for s in samples), default=0) or 1
    scale = min(int(32767 * 0.97) / peak, 4.0)
    return array.array(
        "h", (max(-32768, min(32767, round(s * scale))) for s in samples)
    ).tobytes()


def _generate(client: genai.Client, direction: str, script: str, voice: str) -> tuple[bytes, int]:
    last: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        if attempt:
            time.sleep(5 * attempt)
        try:
            resp = client.models.generate_content(
                model=TTS_MODEL,
                contents=f"{direction}\n\n{script}",
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                        )
                    ),
                ),
            )
            part = resp.candidates[0].content.parts[0].inline_data
            if not part.data:
                raise ValueError("빈 오디오 응답")
            return part.data, _pcm_rate(part.mime_type)
        except Exception as e:  # noqa: BLE001 — 429/일시 오류 재시도 후 최종 보고
            last = e
            # 키/프로젝트 설정 문제는 재시도 무의미 — 즉시 중단하고 안내.
            if any(x in str(e) for x in ("SERVICE_DISABLED", "BILLING_DISABLED")):
                break
    hint = ""
    if any(x in str(last) for x in ("SERVICE_DISABLED", "BILLING_DISABLED", "PERMISSION_DENIED")):
        hint = (
            "\n힌트: Vertex express 키(AQ.…)는 aiplatform TTS를 프로젝트에 aiplatform API"
            "\n  활성화 + 결제(billing) 연결이 모두 돼야 쓴다(TTS는 무료 티어 없음)."
            "\n  → 더 간단한 길: https://aistudio.google.com 에서 AI Studio 키(AIza…) 발급"
            "\n    (프리뷰 TTS 무료 티어 · billing 불필요) 후:"
            "\n    GEMINI_API_KEY=AIza… backend/.venv/bin/python infra/gpu-server/build_persona_refs_gemini.py"
        )
    raise RuntimeError(f"생성 실패({1 + MAX_RETRIES}회): {last}{hint}") from last


def main() -> None:
    key = _api_key()
    client = genai.Client(vertexai=key.startswith("AQ."), api_key=key)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for name, voice, direction, script in PERSONAS:
        pcm, rate = _generate(client, direction, script, voice)
        out = OUT_DIR / f"{name}.wav"
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(_normalize(pcm))
        dur = len(pcm) / 2 / rate
        print(f"[{name}] voice={voice} {dur:.1f}s {rate}Hz -> {out.relative_to(HERE)}")

    print("\n청취 검수 후: cp voices/refs_gemini/*.wav voices/refs/ → 프로파일 (3)단계 재계산 → 재기동")


if __name__ == "__main__":
    main()

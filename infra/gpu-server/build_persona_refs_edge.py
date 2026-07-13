#!/usr/bin/env python
"""페르소나 레퍼런스 후보 생성 — Path B-3 (edge-tts 부트스트랩).

MOSS 라우트(Path B-2)는 생성 안정성 문제(문장 중간 truncation·저품질)로 제외됐고,
이 스크립트는 Microsoft Edge 신경망 TTS(edge-tts)의 **서로 다른 실제 화자**들로
페르소나별 레퍼런스 후보를 만든다. 핵심 근거: VoxCPM2는 화자 정체성(음색·음역대)을
클로닝하므로, 같은 목소리의 피치시프트(캐리커처 라우트의 한계)가 아니라 애초에
다른 화자를 레퍼런스로 줘야 "꼰대는 낮게/잼민은 높게" 방향이 산다.

페르소나당 후보 2~3개(캐스팅 매트릭스)를 voices/refs_edge/candidates/ 에 생성하고,
eval_persona_voices.py 로 채점 → 청취 검수로 5종을 골라 voices/refs_edge/{persona}.wav
로 승격 → refs/ 교체 → 프로파일 재계산(persona_voices.md (3)단계) → 재기동.

대본은 기존 확정본을 클로닝 관점에서 개선한 v2다(音素 커버리지 보강, 운율 마커를
대본에 직접 배치 — VoxCPM2는 레퍼런스의 발화 스타일까지 클로닝하므로 대본이 곧
간접 프롬프트다). 문장 경계로 끝나 truncation 검출이 쉽고, 10~20s 안에 들어온다.

의존성: pip install edge-tts imageio-ffmpeg   (ffmpeg 미설치 환경 폴백은 stt.py와 동일)
실행:   python build_persona_refs_edge.py            # 전체 매트릭스
        python build_persona_refs_edge.py kkondae    # 특정 페르소나만
주의:   edge-tts는 비공식 API(ToS 그레이존) — 1회성 부트스트랩 용도로만 쓴다.
"""

from __future__ import annotations

import array
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import edge_tts

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "voices" / "refs_edge" / "candidates"
SR = 48000  # refs 관례: 48kHz mono PCM16, 피크 0.97
MAX_RETRIES = 2

# ── 페르소나 대본 v2 (클로닝 최적화) ─────────────────────────────────────────
# v1(build_persona_voices.sh 확정본) 대비: 音素 다양성 보강, 쉼표·말줄임표로 운율
# 마커를 대본에 직접 심음(느긋함/뜸/머뭇거림이 레퍼런스 오디오에 실제로 담기게).
# 프로파일 재계산 시 ref_text 로도 이 원문을 쓴다(오디오↔텍스트 정합).
SCRIPTS: dict[str, str] = {
    "egen": (
        "아, 발표 정말 잘 들었어요. 흐름이 차분해서 듣는 내내 편안했고, "
        "준비 많이 하신 게 느껴졌어요. 다만 두 번째 결과 부분이 조금 더 궁금했는데요, "
        "그렇게 판단하신 배경을 편하게 말씀해 주실 수 있을까요?"
    ),
    "teto": (
        "핵심만 짚겠습니다. 방금 그 수치, 출처가 어디죠? 표본은 몇 개였고, "
        "검증은 어떻게 했습니까? 결론이 먼저고 근거는 그다음입니다. "
        "지금 설명으로는 설득이 안 돼요. 다시 정리해서 말해 보세요."
    ),
    "kkondae": (
        "어허, 내가 이 바닥에서만 삼십 년이야. 요즘 친구들은 말이지… 기본기가 없어요, "
        "기본기가. 그 정도 자료 조사로 발표가 되겠나? 자네, 이거 처음부터 다시 해 오게."
    ),
    "mungcheong": (
        "어… 그러니까, 음… 제가 잘 이해를 못 했는데요. 이게… 앞에서 말씀하신 거랑 "
        "같은 건가요? 아, 잠깐만요, 질문이 뭐였더라… 아무튼 그 부분만 조금 더 "
        "쉽게 설명해 주시면 안 될까요?"
    ),
    "jammin": (
        "에이, 그거 저도 아는 건데요? 그거 완전 기본 아니에요? 근데 발표자님, "
        "아까 그거 살짝 틀린 것 같은데요? 제 말이 맞잖아요, 맞죠? 아님 말고요. "
        "기분 나쁘셨다면 어쩔 수 없고요."
    ),
}

# ── 캐스팅 매트릭스: (태그, edge-tts voice, rate, pitch) ─────────────────────
# 프리셰이핑(rate/pitch)은 "다른 화자" 확보가 목적이지 방향 보증이 아니다 —
# 방향은 클로닝 후 실측(F0)으로 확인하고 부족분만 backend DSP(Layer 3)로 보정.
# 최종 5종을 고를 때 같은 화자를 두 페르소나에 쓰지 말 것(음색 충돌 — 특히
# egen/jammin이 둘 다 SunHi 계열이 되지 않게).
# 다국어 화자(Ava·Brian·Florian 등)는 한국어 억양 리스크가 있어 후보로만 넣는다.
CANDIDATES: dict[str, list[tuple[str, str, str, str]]] = {
    "egen": [
        ("sunhi_soft", "ko-KR-SunHiNeural", "-8%", "+0Hz"),
        ("ava_warm", "en-US-AvaMultilingualNeural", "-5%", "+0Hz"),
    ],
    "teto": [
        ("injoon_brisk", "ko-KR-InJoonNeural", "+10%", "-5Hz"),
        ("hyunsu_brisk", "ko-KR-HyunsuMultilingualNeural", "+12%", "-10Hz"),
        ("andrew_brisk", "en-US-AndrewMultilingualNeural", "+8%", "+0Hz"),
    ],
    "kkondae": [
        # 대본 v2가 짧아진 만큼 감속을 완화(-15~-18 → -10~-12) — 20s 대역 유지 목적.
        # 느린 페이스 자체는 말줄임표·쉼표 pause가 이미 담당한다(침묵 30~50% 실측).
        ("injoon_low", "ko-KR-InJoonNeural", "-10%", "-30Hz"),
        ("hyunsu_low", "ko-KR-HyunsuMultilingualNeural", "-12%", "-25Hz"),
        ("florian_low", "de-DE-FlorianMultilingualNeural", "-10%", "-20Hz"),
    ],
    "mungcheong": [
        ("hyunsu_hes", "ko-KR-HyunsuMultilingualNeural", "-10%", "+10Hz"),
        ("brian_hes", "en-US-BrianMultilingualNeural", "-8%", "+0Hz"),
        ("emma_hes", "en-US-EmmaMultilingualNeural", "-10%", "+0Hz"),
    ],
    "jammin": [
        ("sunhi_kid", "ko-KR-SunHiNeural", "+15%", "+45Hz"),
        ("ava_kid", "en-US-AvaMultilingualNeural", "+18%", "+50Hz"),
        ("emma_kid", "en-US-EmmaMultilingualNeural", "+15%", "+40Hz"),
    ],
}


def _ffmpeg() -> str:
    if path := shutil.which("ffmpeg"):
        return path
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _normalize_peak(pcm: bytes) -> bytes:
    """피크 0.97 정규화(refs 관례). 증폭 상한 4배."""
    samples = array.array("h")
    samples.frombytes(pcm)
    peak = max((abs(s) for s in samples), default=0) or 1
    scale = min(int(32767 * 0.97) / peak, 4.0)
    return array.array(
        "h", (max(-32768, min(32767, round(s * scale))) for s in samples)
    ).tobytes()


async def _synth_mp3(voice: str, text: str, rate: str, pitch: str, dst: Path) -> None:
    last: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        if attempt:
            await asyncio.sleep(3 * attempt)
        try:
            await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(dst))
            if dst.stat().st_size > 1000:
                return
            raise RuntimeError(f"출력이 비정상적으로 작음: {dst.stat().st_size}B")
        except Exception as e:  # noqa: BLE001 — 네트워크/서비스 오류 일괄 재시도
            last = e
    raise RuntimeError(f"edge-tts 합성 실패({1 + MAX_RETRIES}회): {voice}: {last}") from last


def _mp3_to_wav48k(ffmpeg: str, mp3: Path, wav: Path) -> float:
    """mp3 → 48kHz mono PCM16 wav + 피크 정규화. 재생 길이(초) 반환."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(mp3),
             "-ar", str(SR), "-ac", "1", "-sample_fmt", "s16", str(tmp_path)],
            check=True,
        )
        with wave.open(str(tmp_path), "rb") as r:
            params = r.getparams()
            frames = r.readframes(r.getnframes())
        with wave.open(str(wav), "wb") as w:
            w.setparams(params)
            w.writeframes(_normalize_peak(frames))
        return params.nframes / params.framerate
    finally:
        tmp_path.unlink(missing_ok=True)


async def main() -> None:
    only = set(sys.argv[1:])
    if unknown := only - set(SCRIPTS):
        sys.exit(f"알 수 없는 페르소나: {sorted(unknown)} (사용 가능: {sorted(SCRIPTS)})")

    ffmpeg = _ffmpeg()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, list[dict]] = {}

    for persona, script in SCRIPTS.items():
        if only and persona not in only:
            continue
        entries = []
        for tag, voice, rate, pitch in CANDIDATES[persona]:
            name = f"{persona}__{tag}"
            wav_path = OUT_DIR / f"{name}.wav"
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                mp3_path = Path(tmp.name)
            try:
                await _synth_mp3(voice, script, rate, pitch, mp3_path)
                dur = _mp3_to_wav48k(ffmpeg, mp3_path, wav_path)
            finally:
                mp3_path.unlink(missing_ok=True)
            entries.append({
                "file": wav_path.name, "voice": voice,
                "rate": rate, "pitch": pitch, "duration_sec": round(dur, 1),
            })
            print(f"[{name}] {voice} rate={rate} pitch={pitch} -> {dur:.1f}s")
        manifest[persona] = entries

    manifest_path = OUT_DIR / "manifest.json"
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    existing.update(manifest)
    manifest_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    print(f"\n{sum(len(v) for v in manifest.values())}개 후보 생성 완료 → {OUT_DIR}")
    print("다음: python eval_persona_voices.py voices/refs_edge/candidates  (채점)")
    print("      → 청취 검수 → 페르소나당 1개를 voices/refs_edge/{persona}.wav 로 승격")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env bash
# 페르소나 음성 프로파일 생성 (VoxCPM2, 5종) — 설계: persona_voices.md
#
# VoxCPM2는 지시(instruction)로 말투를 못 바꾸는 레퍼런스 클로닝 전용이라, 사람
# 레퍼런스 클립이 없을 때는 default 음성으로 페르소나 대사를 합성한 뒤 librosa로
# 피치/템포를 페르소나별로 변형해 캐리커처 레퍼런스를 만든다(외부 자산 0, 동의 이슈 0).
#
# 단계: (1) TTS default로 base 합성  (2) 피치/템포 변형 → voices/refs/*.wav
#       (3) CPU에서 프로파일 사전계산 → voices/profiles/*.safetensors + manifest
# 요구: TTS 서버가 8100에 떠 있어야 함(1단계). 이후 start_tts.sh 재기동으로 반영.
# 사람 레퍼런스가 생기면 voices/refs/{persona}.wav만 교체하고 (3)만 다시 돌리면 된다.
set -euo pipefail
cd "$(dirname "$0")"
source .venv-tts/bin/activate
mkdir -p voices/refs voices/base voices/profiles

echo "=== (1)+(2) base 합성 + 피치/템포 변형 ==="
python - <<'PY'
import json, subprocess, os
import numpy as np, soundfile as sf, librosa
TTS="http://127.0.0.1:8100/v1/audio/speech"; SR=48000
# (persona, script, pitch_semitones, tempo_rate) — 피치 사다리로 5종 음색 분리
P=[
 ("egen",       "아, 발표 정말 잘 들었어요. 준비 많이 하신 게 느껴져서 좋았어요. 다만 이 부분이 조금 더 궁금했는데요, 이렇게 생각하신 이유를 편하게 말씀해 주실 수 있을까요?", +2.5, 1.00),
 ("teto",       "핵심만 짚죠. 방금 그 수치, 근거가 뭡니까? 결론이 먼저고 이유는 그다음이에요. 지금 설명으로는 설득이 안 됩니다. 다시 정리해서 말해 보세요.", -2.0, 1.05),
 ("kkondae",    "어허, 내가 이 바닥 삼십 년인데 말이야. 요즘 친구들은 기본기가 없어. 그 정도 자료로 발표가 되나? 내가 젊었을 땐 이런 건 밤새서라도 다 외웠어. 자네, 이거 다시 해 와.", -4.0, 0.90),
 ("mungcheong", "어, 그러니까, 음, 제가 잘 이해를 못 했는데요, 이게 그 앞에 말한 거랑 같은 건가요? 아 잠깐, 질문이 뭐였지, 아무튼 그거 좀 더 쉽게 설명해 주실 수 있어요?", 0.0, 0.92),
 ("jammin",     "에이 그거 저도 알아요. 그거 완전 기본 아님? 근데 발표자님 그거 틀린 거 같은데요? 제 말이 맞잖아요. 기분 나쁘셨다면 죄송하구요.", +5.0, 1.12),
]
for name, text, steps, rate in P:
    base=f"voices/base/{name}.wav"
    payload=json.dumps({"model":"openbmb/VoxCPM2","input":text,"voice":"default"})
    r=subprocess.run(["curl","-sf",TTS,"-H","Content-Type: application/json","-d",payload,"--output",base])
    if r.returncode!=0 or not os.path.exists(base):
        raise SystemExit(f"[{name}] TTS 합성 실패 — 8100 서버 확인")
    y,sr=librosa.load(base, sr=SR, mono=True)
    if steps: y=librosa.effects.pitch_shift(y, sr=sr, n_steps=steps)
    if abs(rate-1.0)>1e-3: y=librosa.effects.time_stretch(y, rate=rate)
    y=(y/(np.max(np.abs(y)) or 1.0)*0.97).astype(np.float32)
    sf.write(f"voices/refs/{name}.wav", y, sr, subtype="PCM_16")
    print(f"[{name}] pitch{steps:+} rate{rate} -> voices/refs/{name}.wav")
PY

echo "=== (3) 프로파일 사전계산 (CPU) ==="
PC=vllm-omni/examples/online_serving/text_to_speech/voxcpm2/precompute_custom_voice.py
for p in egen teto kkondae mungcheong jammin; do
  CUDA_VISIBLE_DEVICES="" python "$PC" --model openbmb/VoxCPM2 --output-dir voices/profiles \
    --voice-name "$p" --ref-audio "voices/refs/$p.wav" --mode reference --device cpu >/dev/null
  echo "[$p] profile 생성"
done
echo "완료 → voices/profiles/. start_tts.sh 재기동으로 반영."

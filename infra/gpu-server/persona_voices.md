# VoxCPM2 페르소나 음성 설계 (5종)

> 상태: **설계 완료 · 음성 자산 미확보(제작 대기)**. 작성 2026-07-11 (팀원3).
> 대상 페르소나 enum: `egen · teto · kkondae · mungcheong · jammin`
> (db-schema `questioner_persona`, api-spec §6 `QuestionerPersona`).

## 이 문서의 위치 (중요한 기술 제약)

VoxCPM2는 **텍스트 지시(instruction)로 말투를 바꾸지 못한다.** 어댑터가 실제로
쓰는 입력은 `text / ref_audio / ref_text / voice_profile`뿐이다
(`serving_speech.py:_build_voxcpm2_prompt`, `voxcpm2_talker.build_voxcpm2_prompt`).
`/v1/audio/speech`의 `instructions` 필드는 VoxCPM2 요청에서 **검증만 되고 생성에는
반영되지 않는다**(길이 토큰 계산용). 즉 VoxCPM2는 **레퍼런스 오디오 제로샷 클로닝**
전용이다. `instructions` 기반 음성 스타일 제어는 Qwen3-TTS / MOSS-VoiceGenerator
계열 모델의 기능이며 현재 배포돼 있지 않다.

**따라서 페르소나 5종을 *실제로 다른 목소리*로 만들려면 페르소나별 레퍼런스 wav가
반드시 필요하다.** VoxCPM2의 `default` 하나로는 음색을 못 바꾼다. 이 문서는 그
레퍼런스를 **녹음/확보할 때의 목표 스펙**과, 확보 후 **서버에 물리는 방법**을 정의한다.
아래 "지시 프롬프트" 칼럼은 Qwen3-TTS 라우트(스트레치 골, workflow 리스크표)를
택할 경우 그대로 재사용할 수 있게 함께 적어 둔다.

---

## 페르소나별 음성 설계표

각 페르소나는 **질문하는 AI 청중**의 캐릭터다(발표자를 상대로 질문/꼬리질문을 던짐).
`질문 전략(strategy)`은 별도 축이라 랜덤 배분되지만, 페르소나가 자연스레 어울리는
전략을 "전략 친화"에 적어 둔다.

### 1. `egen` — 에겐 (감성·섬세형)

- **밈 정의:** 에스트로겐에서 파생. 공감 능력이 높고 감정 표현이 풍부하며 상대의
  기분을 먼저 배려하는 섬세한 성향. (성별 무관, 부드러운 톤)
- **목표 음색:** 20~30대, 부드럽고 따뜻한 중고음, 느긋한 페이스, 끝을 올리며
  배려하는 억양. 공격성 0, 미소 섞인 발화.
- **레퍼런스 스크립트(녹음용, ~15s):**
  > "아, 발표 정말 잘 들었어요. 준비 많이 하신 게 느껴져서 좋았어요. 다만 이 부분이
  > 조금 더 궁금했는데… 혹시 이렇게 생각하신 이유를 편하게 말씀해 주실 수 있을까요?"
- **지시 프롬프트(Qwen3-TTS용):** "따뜻하고 공감적인 20대 목소리, 부드럽고 배려하는
  말투, 느긋한 속도, 끝을 살짝 올리는 억양." / EN: "warm, empathetic young adult,
  soft and gentle, unhurried, reassuring."
- **전략 친화:** 큰그림, 기초개념 (부드럽게 근거를 물음).

### 2. `teto` — 테토 (직설·추진형)

- **밈 정의:** 테스토스테론에서 파생. 직설적이고 결단력 있으며 추진력이 강한 성향.
- **목표 음색:** 30대, 낮고 단단한 중저음, 빠르고 또렷한 페이스, 단정적 억양.
  군더더기 없이 핵심을 찌른다.
- **레퍼런스 스크립트(~15s):**
  > "핵심만 짚죠. 방금 그 수치, 근거가 뭡니까? 결론이 먼저고 이유는 그다음이에요.
  > 지금 설명으로는 설득이 안 됩니다. 다시 정리해서 말해 보세요."
- **지시 프롬프트:** "낮고 단단한 30대 남성 목소리, 직설적이고 자신감 있는 말투,
  빠르고 단정적." / EN: "low, firm, assertive adult male, blunt and confident, brisk."
- **전략 친화:** 디테일 추궁, 수치검증.

### 3. `kkondae` — 꼰대 (훈계·권위형)

- **밈 정의:** 나이·경험을 앞세워 훈계하고 가르치려 드는 권위적 유형("요즘 젊은
  것들은…"). 상대를 낮잡아 보는 태도.
- **목표 음색:** 50~60대 남성, 낮고 굵은 저음, 느리고 뜸 들이는 페이스, 혀 차는 듯한
  훈계조, 끝을 내리누르는 억양.
- **레퍼런스 스크립트(~18s):**
  > "어허, 내가 이 바닥 30년인데 말이야. 요즘 친구들은 기본기가 없어. 그 정도
  > 자료로 발표가 되나? 내가 젊었을 땐 이런 건 밤새서라도 다 외웠어. 자네, 이거
  > 다시 해 와."
- **지시 프롬프트:** "50대 후반 남성, 낮고 굵은 목소리, 느리고 훈계하는 말투,
  거들먹거리며 가르치는 어조." / EN: "late-50s man, deep and slow, condescending,
  lecturing, patronizing."
- **전략 친화:** 기초개념(면박성), 디테일 추궁.

### 4. `mungcheong` — 멍청 (어리숙·엉뚱형)

- **밈 정의:** 맥락을 잘 못 잡고 엉뚱하거나 지나치게 기초적인 질문을 하는 어리숙한
  유형. 악의는 없음.
- **목표 음색:** 20대, 다소 높고 물렁한 톤, 느리고 머뭇거리는 페이스,
  "어…", "음…" 간투사 많고 끝을 흐리는 억양. 확신 없는 발화.
- **레퍼런스 스크립트(~15s):**
  > "어… 그러니까… 음… 제가 잘 이해를 못 했는데요, 이게… 그 앞에 말한 거랑 같은
  > 건가요? 아 잠깐, 질문이 뭐였지… 아무튼 그거 좀 더 쉽게 설명해 주실 수 있어요…?"
- **지시 프롬프트:** "20대 목소리, 느리고 머뭇거리며 자신 없는 말투, 간투사가 많고
  끝을 흐림." / EN: "young adult, slow, hesitant, unsure, lots of filler, trailing off."
- **전략 친화:** 기초개념 (naive한 재질문).

### 5. `jammin` — 잼민 (초딩·건방형)

- **밈 정의:** 트위치 유래 신조어. 초등학생 저연령층 캐릭터. 아는 척·건방지고
  신조어/드립을 남발하며 지기 싫어함. (어원: 어린 남자아이 TTS "재민")
- **목표 음색:** 10~12세 남자아이, 높고 앳된 톤, 빠르고 촐랑거리는 페이스,
  건방지고 까부는 억양, 말끝에 힘 줌.
- **레퍼런스 스크립트(~13s):**
  > "에이 그거 저도 알아요~ ㅋㅋ 그거 완전 기본 아님? 근데 발표자님 그거 틀린 거
  > 같은데요? 제 말이 맞잖아요. 기분 나쁘셨다면 죄송하구요~"
- **지시 프롬프트:** "10~12세 남자아이 목소리, 높고 앳되며 빠르고 건방진 말투,
  까불거리는 어조." / EN: "10-12yo boy, high-pitched, fast, cocky, cheeky, bratty."
- **전략 친화:** 수치검증(트집), 디테일 추궁(어설픈 반박).

---

## 음성 자산 확보 후 설치 방법 (VoxCPM2 라우트)

레퍼런스 wav 5개가 준비되면(각 10~20s, 48kHz mono 권장, 잡음 적을수록 좋음):

1. `voices/refs/{persona}.wav` 로 배치 (egen/teto/kkondae/mungcheong/jammin).
2. 프로파일 사전계산 → `custom_voice_dir` 생성:
   ```bash
   # vllm-omni 예제 스크립트 사용. 각 페르소나마다 1회.
   python vllm-omni/examples/online_serving/text_to_speech/voxcpm2/precompute_custom_voice.py \
     --model openbmb/VoxCPM2 --output-dir voices/profiles \
     --voice-name egen --ref-audio voices/refs/egen.wav --mode reference
   # teto/kkondae/mungcheong/jammin 반복
   ```
   → `voices/profiles/`에 `{persona}.safetensors` + `custom_voice_manifest.json` 생성.
3. 서버에 물리기 — 벤더 파일(`vllm_omni/deploy/voxcpm2.yaml`) 수정 없이 `hf_overrides`로:
   `start_tts.sh`의 `vllm serve …`에 추가
   ```
   --hf-overrides '{"custom_voice_dir": "/abs/path/to/voices/profiles"}'
   ```
   (서버 `_get_custom_voice_dir()`가 `hf_config.custom_voice_dir`를 읽어 기동 시
   프로파일을 로드한다. 재기동 1회 필요.)
4. 확인: `curl … -d '{"model":"openbmb/VoxCPM2","input":"테스트","voice":"kkondae"}'`가
   200을 반환하고, `voice` 미지정/`default`와 음색이 다른지 청취.
5. 백엔드 매핑: 팀원2 라우터에서 `question.persona → voice`를 그대로 1:1
   (`egen→egen` …) 전달. 실패 시 `default` 폴백.

> **주의:** wav가 없으면 위 2~4단계는 실행 불가하며, `default` 외 voice는 서버가
> `400 Invalid voice`로 거부한다(현재 상태). 그래서 이 스텝은 자산 확보가 선행돼야 한다.

## Qwen3-TTS 라우트(스트레치)를 택할 경우

레퍼런스 오디오 없이 위 "지시 프롬프트" 칼럼만으로 5종을 만들 수 있으나, 상주 모델을
1개 더 올려야 하고(VRAM 예산 재배분 필요) 현재 infra 구성(VoxCPM2 단일)에서 벗어난다.
이 경우 이 문서의 음색/스크립트 설계는 지시 프롬프트 튜닝의 출발점으로 재사용한다.

## 출처 (페르소나 리서치)

- 에겐/테토: [나무위키 테토-에겐 성격유형](https://namu.wiki/w/%ED%85%8C%ED%86%A0-%EC%97%90%EA%B2%90%20%EC%84%B1%EA%B2%A9%20%EC%9C%A0%ED%98%95), [네이트뉴스](https://news.nate.com/view/20250324n11838)
- 잼민이/꼰대: [나무위키 잼민이](https://namu.wiki/w/%EC%9E%BC%EB%AF%BC%EC%9D%B4)

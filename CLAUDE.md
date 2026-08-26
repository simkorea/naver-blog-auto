# 이 저장소에서 일할 때

## 사용자에 대해

개발자가 아니다. 부동산 컨설턴트이고, **고객에게 소송을 당한 상태**다.
증거파인더는 그 방어에 쓸 도구다. 자료는 실제 소송 자료이므로 잃으면 안 된다.

- 한국어로 대화한다. 전문용어는 풀어서 쓴다.
- 명령어를 대신 실행해 주는 것이 이 도구를 쓰는 이유다. "이걸 치세요"로 넘기지 말고 직접 실행한다.
- 화면에 오류가 뜨면 **추측하지 말고 실제 설치된 라이브러리 소스를 열어서** 확인한다.
  이 저장소의 실패 대부분이 추측으로 고치다 생긴 왕복이었다.

## 두 개의 프로그램이 한 저장소에 있다

| | 파일 | 성격 |
|---|---|---|
| 네이버 블로그 자동화 | `step1_generate.py`, `step2_upload.py`, `naver_news.py`, `image_fetcher.py`, `expert_instruction.md` | **완성됨. 손대지 말 것** |
| 증거파인더 | `evidence/`, `tests/` | 작업 대상 |

블로그 파일은 사용자가 쓰고 있는 것이다. 증거파인더 작업 중에 건드리지 않는다.
`image_fetcher.py` 의 EasyOCR 인스턴스는 증거파인더와 공유하므로 **읽기만** 한다.

## 지금 상태

설치는 끝났다. 사용자 PC: 한국어 윈도우 11, RTX 5060 Laptop, cu128.

```
python evidence/setup_check.py          현재 상태 확인
python evidence/setup_check.py --go     남은 준비 (모델 받기 + 자체 점검 3분)
python tests/run_all.py                 회귀 159항목
```

마지막으로 확인된 것: 음성 인식·의미 검색·OCR 모델 완료, 화자 분리 모델은
`Weights only load failed` 로 두 번 실패한 뒤 `bf0b413` 에서 고쳤으나
**사용자 PC에서 아직 확인되지 않았다.** 이것이 첫 번째 할 일이다.

## 절대 하지 말 것

1. **torch 계열을 올리지 않는다.** `torch 2.8.0 / torchvision 0.23.0 / torchaudio 2.8.0`
   에 고정되어 있다. torchaudio 2.9 가 `AudioMetaData` 와 `info()` 를 걷어냈는데
   pyannote 3.x 가 그것을 쓴다. 올리면 화자 분리가 죽는다.
   `pip install -U` 를 무심코 실행하지 않는다.
2. **`torchcodec` 를 깔려고 하지 않는다.** 윈도우용 배포판이 없다. pyannote 4.x 만
   요구하므로 3.x 로 고정해 문제 자체를 없앴다.
3. **Smart App Control 을 끄라고 하지 않는다.** 윈도우 재설치 없이는 되돌릴 수 없다.
   `.bat` 이 막히면 `python ...` 을 직접 실행한다.
4. **원본 증거 파일을 수정하지 않는다.** `evidence/integrity.py` 의 `guard_not_original()`
   이 막지만, 애초에 시도하지 않는다.
5. **증거 DB 를 지우거나 옮기지 않는다.** 위치는 `python evidence/setup_check.py` 로 확인.

## 이 프로그램에서 이미 밟은 지뢰

같은 것을 다시 밟지 않도록. 전부 실제로 터진 것이다.

| 증상 | 원인 | 해결 |
|---|---|---|
| 콘솔이 첫 줄에서 죽음 | 한국어 윈도우 cp949 에 `✓ ✗ ═` 가 없음 | `evidence/console.py` 를 CLI 진입점 맨 앞에서 호출 |
| `.bat` 이 안 열림 | LF 줄바꿈 + Smart App Control | `.gitattributes` 에 `*.bat text eol=crlf`, python 직접 실행 |
| pip `UnicodeDecodeError` | requirements 를 cp949 로 읽음 | `requirements-evidence.txt` 는 **ASCII 전용** 유지 |
| GPU 인식되는데 느림 | 다른 패키지가 torch 를 CPU 빌드로 덮어씀 | 설치 끝에 `torch.cuda.is_available()` 확인, `--repair` |
| `use_auth_token` 오류 | pyannote 3.x ↔ huggingface_hub 1.x | `diarize._ensure_hf_compat()` |
| `Weights only load failed` | torch 2.6 기본값 변경 + lightning 이 `weights_only` 를 **명시적으로** 넘김 | `diarize._allow_full_checkpoint_load()` — 명시값도 덮어씀 |
| 새 ZIP 받으면 인증키·DB 사라짐 | 윈도우가 `... (2)`, `(3)` 새 폴더에 품 | 자료를 `~/EvidenceFinder` 로 분리 (`config._data_path`) |

## 검증 규칙

**상상한 호출 방식이 아니라 실제 호출 방식으로 시험한다.**
`_allow_full_checkpoint_load` 를 두 번 잘못 고친 원인이 이것이다.
첫 수정은 "부르는 쪽이 정했으면 존중"이었는데, 정작 lightning 은 항상 명시적으로
넘기고 있었다. 검증은 통과했지만 실제로는 아무 일도 하지 않았다.

고친 뒤에는 **고치기 전 상태로 되돌리면 그 검증이 실패하는지** 확인한다.
실패하지 않으면 그 검증은 아무것도 지키지 못한다.

```
python tests/run_all.py     # 커밋 전 항상. 159항목, 1초.
```

이 컨테이너 밖에서만 확인 가능한 것: Whisper 한국어 품질, pyannote 정확도,
법제처 실제 응답, 윈도우 경로·인코딩. 이것들은 사용자 PC에서 직접 돌려 확인한다.

## 다음에 할 일

1. `--go` 로 화자 분리 모델 받기 성공 확인
2. 자체 점검 통과 확인 (`--selftest`, 3분)
3. 녹음 1~2개 + 카톡 1개만 넣어 시범 운영 — **고유명사 사전부터 채운다**
   (사람 이름·상호·단지명. 인식률에 가장 크게 영향)
4. 전사 품질 눈으로 확인 → 사전 보강 → 재실행
5. 만족스러우면 전체 투입 (밤새)
6. 타임라인의 "★ 진술이 바뀐 정황" 부터 검토 → 발췌 담기 → 제출 패키지

자세한 사용법은 `evidence/README_증거분석.md`.

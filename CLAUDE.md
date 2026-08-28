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
python evidence/transcribe.py           녹음 전사 (명령창 · 밤샘용)
python tests/run_all.py                 회귀 276항목 (묶음 7개)
```

마지막으로 확인된 것: 사용자 PC에서 `--go` 로 전 모델(음성 인식·의미 검색·OCR·
화자 분리) 받기 완료. 화자 분리는 `Weights only load failed` 를 고친 뒤에도
실제 GPU·실제 오디오 파일에서만 나오는 문제가 두 개 더 있었다 (speechbrain
`k2_fsa` ImportError, m4a 디코딩 문제 — 위 지뢰 표 참고). 둘 다 고쳤고
사용자 PC에서 `--selftest` 9/9 · `tests/run_all.py` 164/164 통과로 확인됐다.

확인된 성능: RTX 5060 Laptop + large-v3 로 20초 녹음을 9.1초에 전사.
1시간 녹음이면 약 27분.

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
| 화자 분리가 `Lazy import of LazyModule(...k2_fsa...) failed` 로 죽음 | speechbrain 이 k2_fsa 같은 무거운 선택 의존성을 지연 껍데기로 `sys.modules` 에 등록해 둔다. pytorch_lightning 이 체크포인트 로딩 중 `inspect.stack()` 으로 스택을 훑으며 모든 모듈에 `hasattr(m,'__file__')` 을 걸어 이 껍데기까지 건드린다. speechbrain 자신도 "호출자가 inspect.py면 무시" 가드를 넣어 뒀지만 `endswith("/inspect.py")` 로 검사해 윈도우(역슬래시 경로)에서는 전혀 작동하지 않는다 → `k2`(윈도우 배포판 없음)를 실제로 임포트하려다 터짐 | `diarize._defuse_speechbrain_redirects()` — 깨진 껍데기만 미리 찾아 빈 모듈로 교체 |
| 화자 분리가 `LibsndfileError: Format not recognised` (m4a) 로 죽음 | pyannote 는 soundfile(libsndfile)로 읽어 m4a 를 못 엶. Whisper 는 ffmpeg 로 직접 디코딩해서 같은 파일도 성공함 — 로더가 다름 | `diarize.diarize()` 가 전사용 WAV 사본(`preprocess.prepare`)을 재사용하도록 수정 |
| 새 ZIP 받으면 인증키·DB 사라짐 | 윈도우가 `... (2)`, `(3)` 새 폴더에 품 | 자료를 `~/EvidenceFinder` 로 분리 (`config._data_path`) |
| 전사가 멈춘 줄 알고 다시 눌러 "처음부터" 로 보임 | 실제로는 끝난 것을 건너뛰고 남은 것만 하고 있었다(`[1/27]` = 남은 27건 중 1번째). 진짜 결함은 (1) 파일 안 진행률 콜백이 `pipeline`→`audio` 로 전달되지 않아 긴 녹음에서 화면이 안 움직임 (2) "이미 N건 끝남"을 안 보여줌 | `pipeline.run(file_progress=...)` 로 배선 연결, 화면에 막대 두 개 + 남은 시간, `pipeline.already_done()` 표시 |
| 블로그 대시보드를 열었는데 증거파인더가 뜸 | 둘 다 Streamlit 이고 포트를 안 정해 기본값 8501 이 겹침. 증거파인더가 먼저 차지하자 블로그 launcher 가 "대시보드가 이미 실행 중"으로 오판하고 브라우저만 엶. **섞인 것은 없고 화면만 잘못 열린 것** | 증거파인더를 8532 로 고정 (`.streamlit/config.toml` · 실행 인자 · `app.PORT`). 8501 은 먼저 쓰던 블로그에 돌려줌 |

## 검증 규칙

**상상한 호출 방식이 아니라 실제 호출 방식으로 시험한다.**
`_allow_full_checkpoint_load` 를 두 번 잘못 고친 원인이 이것이다.
첫 수정은 "부르는 쪽이 정했으면 존중"이었는데, 정작 lightning 은 항상 명시적으로
넘기고 있었다. 검증은 통과했지만 실제로는 아무 일도 하지 않았다.

고친 뒤에는 **고치기 전 상태로 되돌리면 그 검증이 실패하는지** 확인한다.
실패하지 않으면 그 검증은 아무것도 지키지 못한다.

```
python tests/run_all.py     # 커밋 전 항상. 276항목.
```

이 컨테이너 밖에서만 확인 가능한 것: Whisper 한국어 품질, pyannote 정확도,
법제처 실제 응답, 윈도우 경로·인코딩. 이것들은 사용자 PC에서 직접 돌려 확인한다.

## 다음에 할 일

1. ~~`--go` 로 화자 분리 모델 받기 성공 확인~~ 완료
2. ~~자체 점검 통과 확인 (`--selftest`, 3분)~~ 완료 (9/9)
3. 녹음 1~2개 + 카톡 1개만 넣어 시범 운영 — **고유명사 사전부터 채운다**
   (사람 이름·상호·단지명. 인식률에 가장 크게 영향)
4. 전사 품질 눈으로 확인 → 사전 보강 → 재실행
5. 만족스러우면 전체 투입 (밤새)
6. 타임라인의 "★ 진술이 바뀐 정황" 부터 검토 → 발췌 담기 → 제출 패키지

자세한 사용법은 `evidence/README_증거분석.md`.

## 실제 자료를 넣기 전에 할 검증

`남은_검증.md` 에 6가지가 정리되어 있다. 사용자 실제 녹음 없이도
대부분 확인할 수 있다(ffmpeg 로 만든 시험용 오디오 사용).
순서대로 하나씩, 끝날 때마다 사용자에게 보고한다.

1. ~~오디오 형식 매트릭스~~ — 분류·변환은 웹에서 확인 완료
   (`.3ga`·`.opus` 누락 결함을 찾아 고침). **실제 모델 전사·화자분리만 남음**
2. 법제처 API 실제 조회 — 통째로 미검증
3. 긴 녹음(60분)과 중단·재개
4. 대량 처리 (100개)
5. 카카오톡 내보내기 실제 형식 (PC·모바일)
6. 전체 흐름 한 번 통과

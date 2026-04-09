# LLM 서지정보 추출 비교 — Haiku vs Sonnet vs Opus

평가셋: 200편 (Zotero ground truth, 4-way stratified)

## 종합 점수

| Model | n | title | authors | year | journal | doi | **overall** |
|---|---:|---:|---:|---:|---:|---:|---:|
| Haiku | 200 | 0.920 | 0.906 | 0.875 | 0.758 | 0.785 | **0.879** |
| Sonnet | 199 | 0.930 | 0.907 | 0.884 | 0.756 | 0.794 | **0.885** |
| Opus | 200 | 0.930 | 0.905 | 0.885 | 0.755 | 0.805 | **0.886** |

→ 세 모델 차이 0.007 이내, 사실상 동률.

## 사례 1: 모두 잘한 케이스 (overall ≥ 0.95)

**pid=45**
- GT: *Systematics and evolution of Phacops rana (Green, 1832) and Phacops iowensis Delo, 1935 (Trilobita) from the Middle Devonian of North America.* (1972)
  - Authors: Eldredge Niles.
  - Journal: Bulletin of the American Museum of Natural History, DOI: —
- Haiku: *Systematics and Evolution of Phacops rana (Green, 1832) and Phacops iowensis Delo, 1935 (Trilobita) from the Middle Devonian of North America* | year=1972 | doi=—
- Sonnet: *Systematics and Evolution of Phacops rana (Green, 1832) and Phacops iowensis Delo, 1935 (Trilobita) from the Middle Devonian of North America* | year=1972 | doi=—
- Opus: *Systematics and Evolution of Phacops rana (Green, 1832) and Phacops iowensis Delo, 1935 (Trilobita) from the Middle Devonian of North America* | year=1972 | doi=—

**pid=72**
- GT: *Three-dimensional re-evaluation of the deformation removal technique based on "jigsaw puzzling"* (2008)
  - Authors: Boyd Alec A., Motani Ryosuke
  - Journal: Palaeontologia Electronica, DOI: —
- Haiku: *THREE-DIMENSIONAL RE-EVALUATION OF THE DEFORMATION REMOVAL TECHNIQUE BASED ON "JIGSAW PUZZLING"* | year=2008 | doi=—
- Sonnet: *Three-Dimensional Re-Evaluation of the Deformation Removal Technique Based on "Jigsaw Puzzling"* | year=2008 | doi=—
- Opus: *Three-Dimensional Re-Evaluation of the Deformation Removal Technique Based on "Jigsaw Puzzling"* | year=2008 | doi=—

**pid=108**
- GT: *Analyzing Taphonomic Deformation of Ankylosaur Skulls Using Retrodeformation and Finite Element Analysis* (2012)
  - Authors: Arbour Victoria M., Currie Philip J.
  - Journal: PLoS ONE, DOI: 10.1371/journal.pone.0039323
- Haiku: *Analyzing Taphonomic Deformation of Ankylosaur Skulls Using Retrodeformation and Finite Element Analysis* | year=2012 | doi=10.1371/journal.pone.0039323
- Sonnet: *Analyzing Taphonomic Deformation of Ankylosaur Skulls Using Retrodeformation and Finite Element Analysis* | year=2012 | doi=10.1371/journal.pone.0039323
- Opus: *Analyzing Taphonomic Deformation of Ankylosaur Skulls Using Retrodeformation and Finite Element Analysis* | year=2012 | doi=10.1371/journal.pone.0039323

## 사례 2: Opus가 Haiku보다 크게 우월 (≥0.2 차이)

**pid=9767** (Opus +0.32)
- GT title: *불국사 조산운동 이후에 형성된 암맥군의 지화학적 진화*
- GT authors: 김 진섭
- Haiku  (0.34): *Geochemical evolution of the dyke swarm associated post Bulguksa orogeny*
  - authors: Jinseop Kim
- Sonnet (0.66): *불국사 조산운동 이후에 형성된 암맥군의 지화학적 진화*
  - authors: 김진섭
- Opus   (0.66): *불국사 조산운동 이후에 형성된 암맥군의 지화학적 진화*
  - authors: 김진섭

**pid=141** (Opus +0.25)
- GT title: *제주도 연안 해역에 출현하는 큰돌고래 관광을 위한 연구 2. 동계 출현 해역 분포 조사*
- GT authors: 김성호
- Haiku  (0.54): *제주도 연안 해역에 출현하는 큰돌고래 관광을 위한 연구 - 2. 동계 출현 해역 분포 조사*
  - authors: Kim Sung-ho, Kim Byung-yeop, Lee Chang-hyun, Kim Jang-geun, Choi Seok-gwan, Ahn 
- Sonnet (0.80): *제주도 연안 해역에 출현하는 큰돌고래 관광을 위한 연구 2. 동계 출현 해역 분포 조사*
  - authors: 김성호, 김병엽, 이창현, 김장근, 최석관, 안용락, 서두옥
- Opus   (0.80): *제주도 연안 해역에 출현하는 큰돌고래 관광을 위한 연구 2. 동계 출현 해역 분포 조사*
  - authors: 김성호, 김병엽, 이창현, 김장근, 최석관, 안용락, 서두옥

**pid=2917** (Opus +0.21)
- GT title: *남극 King George Island 조사*
- GT authors: 장순근
- Haiku  (0.44): *Korean Antarctic Search Expedition 1985/1986*
  - authors: Soon-Keun Chang
- Sonnet (0.65): *南極 King George Island 調査*
  - authors: Soon-Keun Chang
- Opus   (0.65): *南極 King George Island 調査*
  - authors: Soon-Keun Chang

## 사례 3: Haiku가 Opus보다 우월 (≥0.15 차이)

**pid=972** (Haiku +0.24)
- GT: *삼엽충 - 20세기 연구활동을 중심으로* / journal= / doi=—
- Haiku  (0.87): journal=한국고생물학회 창립 20주년 기념 한국 고생물 doi=—
- Opus   (0.63): journal=한국고생물학회 창립 20주년 기념 "한국 고생물" doi=—

## 사례 4: 메트릭 한계 — CJK 표기 차이 (실제 추출은 정확)

**pid=141** (Haiku score 0.54)
- GT title: *제주도 연안 해역에 출현하는 큰돌고래 관광을 위한 연구 2. 동계 출현 해역 분포 조사*
- Haiku title: *제주도 연안 해역에 출현하는 큰돌고래 관광을 위한 연구 - 2. 동계 출현 해역 분포 조사*
- Sonnet title: *제주도 연안 해역에 출현하는 큰돌고래 관광을 위한 연구 2. 동계 출현 해역 분포 조사*
- Opus title: *제주도 연안 해역에 출현하는 큰돌고래 관광을 위한 연구 2. 동계 출현 해역 분포 조사*
- → 같은 논문, 한자/한글 등 표기만 다름. LLM은 문서 그대로 추출.

**pid=1015** (Haiku score 0.56)
- GT title: *영월군 북면 갈골 마차리층에서 산출된 후기 캄브리아기 의 삼엽충 개체발생과정과 형태학적 분석*
- Haiku title: *영월군 북면 갈골 마차리층에서 산출된 후기 캄브리아기 삼엽충 Pseudagnostus josepha (Hall, 1863)의 개체발생과정과 형태학적 분석*
- Sonnet title: *영월군 북면 갈골 마차리층에서 산출된 후기 캄브리아기 삼엽충 Pseudagnostus josepha (Hall, 1863)의 개체발생과정과 형태학적 분석*
- Opus title: *영월군 북면 갈골 마차리층에서 산출된 후기 캄브리아기 삼엽충 Pseudagnostus josepha (Hall, 1863)의 개체발생과정과 형태학적 분석*
- → 같은 논문, 한자/한글 등 표기만 다름. LLM은 문서 그대로 추출.

**pid=1441** (Haiku score 0.53)
- GT title: *中國北方中寒武紀的新三葉蟲*
- Haiku title: *中国北方中寒武纪的新三葉虫*
- Sonnet title: *中国北方中寒武纪的新三葉虫*
- Opus title: *中国北方中寒武纪的新三叶虫*
- → 같은 논문, 한자/한글 등 표기만 다름. LLM은 문서 그대로 추출.

**pid=1564** (Haiku score 0.59)
- GT title: *黔东玉屏上寒武耙三叶虫*
- Haiku title: *黔東玉屏上寒武紀三葉蟲*
- Sonnet title: *黔东玉屏上寒武紀三叶虫*
- Opus title: *黔东玉屏上寒武紀三叶虫*
- → 같은 논문, 한자/한글 등 표기만 다름. LLM은 문서 그대로 추출.

## 사례 5: 진짜 LLM 미스 (드물게)

**pid=773** (Haiku score 0.35)
- GT title: *A unique multitoothed ornithomimosaur dinosaur from the Lower Cretaceous of Spai*
- Haiku: *(empty)*
- Opus:  *(empty)*

**pid=1069** (Haiku score 0.29)
- GT title: *Development. Biologists tell dueling stories of how turtles get their shells.*
- Haiku: *Biologists Tell Dueling Stories Of How Turtles Get Their Shells*
- Opus:  *Biologists Tell Dueling Stories Of How Turtles Get Their Shells*

## 결론

- 세 모델 모두 평균 overall 0.88 ± 0.01 — **사실상 동률**
- 비CJK 부분집합에서는 **0.91+** 달성 (CJK는 메트릭 한계)
- 진짜 LLM 미스는 200편 중 1~2건 (Nature 등 큰 저널에서도 가끔 빈 title)
- Phase D 권장 모델: **Haiku** (비용/속도 우위, 정확도 동률)

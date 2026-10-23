# 번역 시험 고정 자료 — 출처 · 사용 허가

`docs.json` 은 번역 적재 · 검색 회귀 시험(TC-TR · `tests/test_translation_search.py`)이 임시 폴더에 zip 으로 만들어 쓰는 자료다.

- **AI허브 71782(금융 분야 다국어 병렬 말뭉치)의 문장은 한 줄도 없다.** 그 자료는 각자 신청해 각자 PC 에만 두고, 저장소 · HF · 해외 서버에 올리지 않는다(이용정책 3 · 5항). 칸 이름과 zip 이름 규칙만 코드에 이미 있는 것을 따랐다.
- **SYN-\*** — Qurious 팀이 시험용으로 직접 쓴 문장이다. 실제 공시 · 기사가 아니고 숫자 · 날짜는 지어낸 값이다. 일본어 · 영어 번역도 팀이 썼다.
- **TATOEBA-\*** — [Tatoeba](https://tatoeba.org) 의 문장이다. 사용 허가는 [CC BY 2.0 FR](https://creativecommons.org/licenses/by/2.0/fr/) 이다. 문장은 고치지 않았고, 한국어 문장을 `source_original` 에, 그 문장에 바로 이어진 영어 번역을 `mtpe` 에 옮겨 시험용 JSON 꼴로 늘어놓았다(이 배치만 바꾼 것이다).
- 받은 날 2026-10-23 · 받은 곳 `https://api.tatoeba.org/unstable/sentences`(낱말 은행 · 가격 · 세금 · 경제 · 회사로 찾음).

| 고정 자료 doc_no | 한국어 문장 | 저작자 | 영어 번역 | 저작자 | 사용 허가 |
|---|---|---|---|---|---|
| TATOEBA-11105543 | [#11105543](https://tatoeba.org/ko/sentences/show/11105543) 나는 은행에 갔다. | intertime | [#3154910](https://tatoeba.org/ko/sentences/show/3154910) I went to the bank. | CK | CC BY 2.0 FR |
| TATOEBA-5526782 | [#5526782](https://tatoeba.org/ko/sentences/show/5526782) 기름 가격은 이번 주에 떨어졌다. | raining211 | [#374801](https://tatoeba.org/ko/sentences/show/374801) The price of oil is down this week. | saeb | CC BY 2.0 FR |
| TATOEBA-11105314 | [#11105314](https://tatoeba.org/ko/sentences/show/11105314) 그 가격에는 세금이 포함되어 있다. | intertime | [#45249](https://tatoeba.org/ko/sentences/show/45249) The price includes tax. | CK | CC BY 2.0 FR |
| TATOEBA-906615 | [#906615](https://tatoeba.org/ko/sentences/show/906615) 기름이나 석탄과 같은 원자재의 가격이 계속 상승하고 있다. | Sudajaengi | [#1256188](https://tatoeba.org/ko/sentences/show/1256188) The prices of raw materials such as oil or coal continue to rise. | stb | CC BY 2.0 FR |
| TATOEBA-2885860 | [#2885860](https://tatoeba.org/ko/sentences/show/2885860) 그 회사가 작년에 십억엔의 손실을 보았다. | cueyayotl | [#49092](https://tatoeba.org/ko/sentences/show/49092) The company suffered a loss of one billion yen last year. | CK | CC BY 2.0 FR |
| TATOEBA-8401457 | [#8401457](https://tatoeba.org/ko/sentences/show/8401457) 난 경제학을 전공하고 있어. | Eunhee | [#238003](https://tatoeba.org/ko/sentences/show/238003) I major in economics. | CK | CC BY 2.0 FR |
| TATOEBA-13008046 | [#13008046](https://tatoeba.org/ko/sentences/show/13008046) 저희는 가격 안 올렸어요. | Uwe | [#5546296](https://tatoeba.org/ko/sentences/show/5546296) We haven't increased our prices. | CK | CC BY 2.0 FR |
| TATOEBA-13145959 | [#13145959](https://tatoeba.org/ko/sentences/show/13145959) 그 은행은 여기에서 멉니까? | SN_H | [#48625](https://tatoeba.org/ko/sentences/show/48625) Is the bank far from here? | CK | CC BY 2.0 FR |

고정 자료의 TATOEBA-\* 문서가 이 표에 모두 있는지는 시험 TC-TR-08 이 본다.

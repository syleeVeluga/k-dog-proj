# K-DOG PR-RP05 구현 Cold Review

버전: v1.0 · 2026-10-08 검증 · 기준: `main / 15c4065` 대비 `veluga/rp05-report-acceptance` · 상태: 독립 검토·수용 수정·관련 재검증 완료

상위: [RP05](K-DOG_PR-RP05_통합검증과교수검토_v1.0_20261007.md), [실행 기록](K-DOG_리포트구현실행기록_v1.0_20261007.md).

별도 리뷰 에이전트가 `c17e150` 종단·브라우저 시험과 기록을 읽기 전용으로 검토했다. 전체 회귀에서 발견한 합성 리허설 수정도 추가로 검토했다. 실제 공급자 호출·원본 자료 변경은 없다.

| ID | 발견과 재현 | 결정·최소 수정 |
| --- | --- | --- |
| RP05-CR01 | P2. 실제 HTML은 갱신하되 PDF만 최초 AI 발급본으로 반환해도 종단 시험이 통과(변조 시험 58.536초 OK). PDF signature/size만으로 사람 최종본 반영 누락을 검출하지 못함 | 수용. 새 PDF와 최초 PDF 차이, 실제 PDF 텍스트의 완료 의견 원문·D39·최종 유형을 무조건 검증 |
| RP05-CR02 | P2. 합성 리허설의 새 공급자가 유효 설문이 있어 `action_capacity=3`인데 빈 actions를 반환해 새 문장 계약에서 거절 | 수용. 실제 공급자를 호출하지 않는 합성 provider에 유효 설문/관찰 fact를 참조한 합성 action 1개 연결. 외부 호출과 합성 응답 수를 구별 |

전체 회귀가 드러낸 리허설의 이전 `Worker(store)` 및 `data-section` 가정도 새 문장 provider 주입·HTML 구조 검사로 수정했다. 리허설 2개, 30.902초에 통과했다. 예산·guard·실제 renderer는 그대로 검증하며 합성 문장을 연구자 확정 문장으로 표시하지 않는다.

PDF 텍스트 검증을 개발 환경에서 빠짐없이 실행하기 위해 dev-only `pypdf==6.19.0`을 manifest/lockfile에 고정했다. 2026-10-08 최신/선택 6.19.0, Python ≥3.9 및 Python 3.14 지원을 [공식 registry](https://pypi.org/project/pypdf/6.19.0/), [선택판 텍스트 추출 API](https://pypdf.readthedocs.io/en/6.19.0/user/extract-text.html), [변경 이력](https://pypdf.readthedocs.io/en/6.19.0/meta/CHANGELOG.html)에서 확인했다. `PdfReader(BytesIO(...)).pages` 및 `extract_text()`만 사용하고 암호화 extra·제품 dependency·다른 고정판은 변경하지 않았다. RP04의 번들 6.10.0 일회성 QA와 이번 dev dependency를 구별한다.

최종 수용 수정 후 종단·리허설·패키징/사용량 23개가 113.810초에 통과했다. 독립 정상 종단은 1개, 60.535초 OK였으며 이전 PDF 재사용 변조는 47.028초에 예상대로 차단했다. 보완된 두 쌍 리허설도 독립 1개, 31.831초 OK였다. 불수용·보류·추가 미해결 발견은 없다.

교수 피드백은 미수령이다. 합성 테스트 통과와 변조 검출은 전문적 문장 품질·실제 공급자 인수 완료를 의미하지 않는다.

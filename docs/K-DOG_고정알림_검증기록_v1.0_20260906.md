# K-DOG 고정 알림 변경·검증 기록

- 작업일: 2026-09-06
- 요청: 긴 페이지에서도 기능 실행 결과와 오류를 인지할 수 있도록 배너 위치 변경.
- 변경: 작업 알림을 공통 React portal 영역에 모으고 화면 오른쪽 위, 헤더 아래에 고정한다. 모바일에서는 화면 폭에 맞춰 표시한다.
- 성공·오류 알림은 닫기 버튼으로 지울 수 있다. 자동 만료 타이머는 없으며 기존 작업별 상태 초기화·화면 종료 시 제거 동작은 유지한다. 처리 중 알림은 작업 완료 시 제거한다.
- 여러 알림은 세로로 쌓이고, 긴 문구는 줄바꿈·내부 스크롤로 표시하여 닫기 버튼을 유지한다. 오류는 `alert`, 일반 알림·처리 상태는 `status` 역할을 사용한다.
- 적용 화면: 로그인, 참가자 작업, 개발 설정, 평가·설명 공급자 설정, 관찰 요청, 리포트 수정·내보내기, 자료 백업. 항목별 오류 목록·상시 설명 문구는 본문에 유지한다.

## 검증

`frontend/`에서 실행:

```powershell
npm run build
npm run test:e2e
```

- 수정 전 새 회귀 테스트에서 하단 키 연결 시험의 성공 알림이 화면 밖에 있음(`viewport ratio 0`)을 재현했다.
- 최종 빌드 통과, 브라우저 테스트 11개 통과.
- 1440px·360px에서 성공/실패 후 스크롤, 알림 간 겹침 방지, 닫기·동일 메시지 재표시, 키보드 닫기, 긴 문구, 가로 넘침, 로그아웃 시 제거를 확인했다.
- 설명 설정·백업 실패가 오류 알림으로 표시되는지 확인했다.
- 기존 등록·설문·영상·평가·리포트·설정 시나리오도 통과했다. 테스트는 별도 임시 서버와 합성 자료를 사용하며 운영 자료·실제 공급자 호출을 사용하지 않는다.
- 데스크톱·모바일 성공/오류 스크린샷을 확인했다. 산출물은 무시되는 `frontend/test-results/notifications-*/notification-*.png`에 저장한다.

## Cold review

- 검증 후 변경 diff와 호출 지점을 다시 읽고, 알림 수명·접근성 역할·닫기 동작·본문 설명과의 구분·좁은 화면을 점검했다.
- 최초 고정 위치가 로그아웃을 가리는 문제를 테스트에서 발견하여 헤더 아래로 조정했다.
- 설명 설정·백업 실패를 일반 알림으로 표시하던 부분을 오류 상태로 분리하고 회귀 검증을 추가했다.
- 보완 후 전체 브라우저 테스트를 다시 통과했으며 잔여 차단 이슈는 없다.

## 라이브러리 확인

2026-09-06 공식 문서·릴리스 안내 및 npm registry의 `npm view <package> version engines peerDependencies --json`으로 확인했다. 새 의존성은 추가하지 않았으며 기존 manifest/lockfile의 고정 버전을 유지했다.

| 패키지 | 최신 안정 / 선택 버전 | 확인 자료 |
| --- | --- | --- |
| React / React DOM | 19.2.8 / 19.2.8 | [React 릴리스](https://github.com/facebook/react/releases), [portal API](https://react.dev/reference/react-dom/createPortal), [React npm](https://www.npmjs.com/package/react), [React DOM npm](https://www.npmjs.com/package/react-dom) |
| Playwright Test | 1.63.0 / 1.63.0 | [릴리스 안내](https://playwright.dev/docs/release-notes), [viewport 검증 API](https://playwright.dev/docs/api/class-locatorassertions#locator-assertions-to-be-in-viewport), [npm](https://www.npmjs.com/package/@playwright/test) |
| Vite | 8.2.2 / 8.2.2 | [지원 버전](https://vite.dev/releases), [npm](https://www.npmjs.com/package/vite) |
| TypeScript | 7.0.2 / 7.0.2 | [공식 배포 안내](https://www.typescriptlang.org/download/), [npm](https://www.npmjs.com/package/typescript) |

실행 Node.js 24.13.0은 Playwright의 Node >=20, Vite의 ^20.19.0 또는 >=22.12.0, TypeScript의 >=16.20.0 조건을 충족한다. React DOM의 React ^19.2.8 peer 조건도 충족한다. 버전 변경에 따른 마이그레이션은 없다.

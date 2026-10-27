# StrCAD 현장조사 — 안드로이드 APK

`mobile/` 웹앱을 Capacitor로 감싼 안드로이드 앱입니다. 화면·기능은 웹앱과 같고, APK에서는 아래가 다릅니다.

| 기능 | 브라우저(웹앱) | APK |
|---|---|---|
| 저장/공유 (.strsv, CSV) | 다운로드 / 웹 공유 | 안드로이드 **공유 창** (카톡·드라이브·메일·내 파일 등) |
| PC와 Wi-Fi 연결 | PC가 띄운 주소로 접속 | 메뉴 › **⚙ PC 주소 설정**에 `192.168.x.x:8765`를 한 번 입력하면 됨 |
| 사진 | 카메라/갤러리 | 카메라/갤러리 (카메라 권한 요청) |
| 오프라인 | 서비스워커 | 앱 안에 모두 내장됨 |

## APK 만들기 (GitHub Actions, PC에 아무것도 설치하지 않음)

1. GitHub에 새 저장소(비공개도 됨)를 만들고 `strcad_cad_analysis` 폴더 전체를 올립니다.
   반드시 `.github/workflows/build-apk.yml` 가 포함되어야 합니다.
2. 저장소의 **Actions** 탭 › **build-apk** › **Run workflow**를 누릅니다. 약 5~8분 걸립니다.
3. 빌드가 끝나면 저장소의 **Releases › apk-latest**에 `StrCAD_survey.apk`가 올라갑니다. 휴대폰에서 이 페이지를 열면 바로 받을 수 있습니다.
   (Actions 실행 화면의 **Artifacts › StrCAD_survey-apk**에서도 받을 수 있습니다.)
   `mobile/`이나 `android-app/`을 고쳐서 push하면 새 APK가 자동으로 만들어집니다.

## 휴대폰에 설치

1. APK를 휴대폰으로 옮깁니다 (카톡 나에게 보내기, USB, 구글드라이브 등).
2. 파일을 누르고 **"출처를 알 수 없는 앱 설치 허용"**을 켠 뒤 설치합니다.
3. 앱 이름은 **StrCAD 현장조사**입니다.

> 이 APK는 디버그 서명입니다. 내부 배포는 문제없습니다. Play 스토어에 올리려면 release 서명 키가 필요합니다
> (`./gradlew assembleRelease` + keystore 설정).

## 직접 빌드하기 (선택: Android Studio가 있는 PC)

```bash
cd android-app
npm install
npm run sync              # ../mobile → www 복사 + cap sync
cd android && ./gradlew assembleDebug
# 결과: android/app/build/outputs/apk/debug/app-debug.apk
```

웹앱(`mobile/`)을 고친 뒤에는 `npm run sync`를 다시 실행하거나, GitHub에 push만 하면 Actions가 새 APK를 만듭니다.

## PC와 같이 쓰기

- **파일로 주고받기:** PC에서 현장조사 › 모바일로 내보내기(.strsv)를 하고 휴대폰으로 보냅니다. 앱에서 📂 열기로 열어 조사한 뒤 💾 저장/공유로 PC에 보내고, PC에서 모바일 가져오기를 합니다.
- **Wi-Fi:** PC에서 현장조사 › Wi-Fi 연결을 켜고, 표시된 주소를 앱의 ⚙ PC 주소 설정에 입력합니다. 그다음 🖥 PC에서 받기 / PC로 보내기를 씁니다.
  같은 공유기에 연결되어 있어야 합니다. Windows 방화벽이 물으면 "허용"을 누릅니다.

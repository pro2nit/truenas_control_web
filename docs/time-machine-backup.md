# TrueNAS Time Machine 공유에 Mac 추가하기

이 문서는 TrueNAS SCALE의 Time Machine 전용 SMB 공유를 여러 Mac에서 사용하는 일반적인 절차를 설명합니다. 계정 암호와 백업 암호화 암호는 이 저장소나 NAS Control에 저장하지 마세요.

## TrueNAS 준비

1. Time Machine용 데이터셋을 만듭니다.
2. 데이터셋에 적절한 quota를 설정합니다.
3. 전용 SMB 사용자를 만들고 데이터셋 접근 권한을 부여합니다.
4. SMB 공유를 만들 때 **Purpose/Preset**을 `Time Machine`으로 선택합니다.
5. SMB 서비스를 시작하고 자동 시작을 켭니다.

일반 파일 공유와 Time Machine 공유는 분리하는 것을 권장합니다. 여러 Mac이 같은 공유를 사용하면 각각 `<Mac 이름>.sparsebundle`을 만들지만 공유 quota는 함께 사용합니다.

TrueNAS 공식 안내: [Adding a Basic Time Machine SMB Share](https://www.truenas.com/docs/scale/shares/smb/setupbasictimemachinesmbshare/)

## 용량 계획

- 한 Mac당 내부 디스크 사용량의 2~3배를 여유 공간으로 잡는 것이 좋습니다.
- 여러 Mac이 하나의 공유를 사용하면 모든 백업과 이전 버전이 같은 quota를 소비합니다.
- 데이터셋 quota와 SMB Time Machine quota를 함께 확인합니다.
- 공유가 가득 차기 전에 TrueNAS 알림과 NAS Control의 남은 용량을 확인합니다.

## Mac에서 연결

1. Mac과 TrueNAS를 같은 LAN에 연결합니다.
2. **시스템 설정 → 일반 → Time Machine**을 엽니다.
3. **백업 디스크 추가**를 선택합니다.
4. TrueNAS의 Time Machine 공유를 선택합니다.
5. 전용 SMB 사용자명과 암호를 입력하고 Keychain 저장을 허용합니다.
6. **백업 암호화**를 켜고 해당 Mac 전용 암호를 암호 관리 앱에 저장합니다.
7. 첫 백업이 끝날 때까지 NAS를 종료하지 않습니다.

공유가 자동으로 보이지 않으면 Finder에서 다음 형식으로 먼저 연결합니다.

```text
smb://<NAS_IP>/<TIME_MACHINE_SHARE>
```

백업 암호화 암호는 SMB 계정 암호와 별개입니다. 이 암호를 잃으면 NAS 관리자도 암호화된 백업을 복원할 수 없습니다.

## 동작 확인

```bash
tmutil destinationinfo
tmutil status
```

백업 중 `tmutil status`에 `Running = 1`이 표시되고 전송 바이트가 증가하면 정상입니다. TrueNAS에서는 **SMB Sessions** 화면 또는 `smbstatus`로 연결과 열린 파일을 확인할 수 있습니다.

NAS Control은 열린 `*.sparsebundle` 파일을 기준으로 다음 정보를 표시합니다.

- 백업 중인 Mac 이름
- SMB 공유와 사용자
- 클라이언트 주소
- 열린 백업 파일 수
- NAS 디스크와 네트워크 처리량

파일이 열려 있어도 실제 복사가 잠시 멈춘 상태일 수 있으므로 처리량과 `tmutil status`를 함께 확인하세요.

## 다른 Mac 추가

각 Mac에서 위 연결 절차를 반복합니다. SMB 계정은 공유할 수 있지만 백업 암호화 암호는 Mac마다 별도로 만들고 안전하게 보관하는 것이 좋습니다.

암호를 다른 Mac으로 전달해야 한다면 메신저나 평문 파일보다 암호 관리 앱의 안전한 공유 기능을 사용하세요. 이 프로젝트의 설정 파일이나 문서에 실제 암호를 적지 마세요.

## 문제 해결

- 공유가 안 보이면 TrueNAS SMB 서비스와 Time Machine 공유가 켜져 있는지 확인합니다.
- `truenas.local` 같은 mDNS 이름이 동작하지 않으면 NAS의 고정 IPv4 주소로 연결합니다.
- 로그인 창이 반복되면 macOS Keychain에 저장된 오래된 SMB 자격 증명을 정리한 뒤 다시 연결합니다.
- 첫 백업 중 연결이 끊기면 NAS 여유 공간, 네트워크 안정성 및 `tmutil status`를 확인합니다.
- 공유가 가득 차면 오래된 백업을 임의로 Finder에서 삭제하지 말고 Time Machine과 TrueNAS의 공식 관리 절차를 따릅니다.
- SMB 계정 암호를 바꾸면 각 Mac의 Keychain 자격 증명도 갱신해야 합니다.
- 백업 암호화 암호는 TrueNAS나 NAS Control에서 복구할 수 없습니다.

macOS 파일 이름 관련 TrueNAS 안내: [Using SMB Shares with macOS Decomposed Unicode](https://www.truenas.com/docs/scale/shares/smb/smbusingdecomposedunicode/)

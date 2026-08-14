# TrueNAS Control Web

TrueNAS SCALE을 안전하게 켜고 끄고, 반복 전원 일정을 관리하며, 스토리지와 시스템 활동을 확인하는 macOS용 자체 호스팅 웹 대시보드입니다.

웹 서버는 설치 Mac의 **Tailscale IPv4 주소와 로컬 포트에만 바인딩**됩니다. Tailscale Serve와 Funnel을 사용하지 않으므로 공개 인터넷이나 일반 LAN 주소에서는 대시보드에 직접 접근할 수 없습니다.

## 주요 기능

- Wake-on-LAN을 이용한 NAS 켜기
- TrueNAS API를 이용한 정상 종료
- 요일별 반복 켜기·끄기 예약과 실행 기록
- ping, TrueNAS Web UI, SMB, 선택적 HTTP 서비스 상태 점검
- 실행 중인 TrueNAS 작업, 풀 검사, iSCSI·SMB 세션 및 열린 파일 확인
- Time Machine `sparsebundle` 활동 자동 감지
- 풀 총용량·사용량·남은 용량 그래픽
- CPU, 메모리, ZFS ARC 캐시, 네트워크, 디스크 I/O 및 장치 온도 표시
- 1분 단위 리소스 기록과 24시간·7일·30일·90일 그래프
- 기간별 CPU·메모리·ARC·온도·네트워크·디스크 피크 시각 요약
- SQLite 데이터 저장, CSRF 방어, 보안 응답 헤더 및 macOS Keychain 비밀정보 보관

활동 정보는 종료 판단을 돕지만 종료 버튼을 자동으로 차단하지 않습니다. 파일 전송 중인지 확인한 후 사용자가 직접 종료 여부를 결정합니다.

## 구성 개요

```text
Tailscale 사용자 ── http://<MAC_TAILSCALE_IP>:8787 ── macOS 호스트
                                                        ├─ Wake-on-LAN ── TrueNAS
                                                        └─ WSS API ────── TrueNAS
```

Wake-on-LAN 패킷은 LAN 브로드캐스트로 전송되므로 **서비스를 실행하는 Mac과 NAS가 같은 LAN에 있어야 합니다.** 대시보드에 접속하는 기기만 같은 tailnet에 있으면 됩니다.

## 요구 사항

- macOS 13 이상을 권장
- Python 3.11 이상
- 로그인된 [Tailscale macOS 앱](https://tailscale.com/download/mac)
- TrueNAS SCALE
- NAS의 고정 IPv4 주소 또는 DHCP 예약
- Wake-on-LAN을 지원하고 BIOS/UEFI에서 활성화된 유선 NIC
- 종료와 리소스 조회를 사용하려면 HTTPS가 구성된 TrueNAS API와 API 키

TrueNAS SCALE 25.04 계열에서 개발·검증했습니다. API 권한과 메서드는 TrueNAS 버전에 따라 달라질 수 있습니다.

## 빠른 설치

```bash
git clone https://github.com/pro2nit/truenas_control_web.git
cd truenas_control_web
./scripts/install.sh
```

처음 설치할 때 다음 값을 묻습니다.

- TrueNAS 고정 IPv4 주소
- Wake-on-LAN 대상 유선 NIC의 MAC 주소
- LAN 브로드캐스트 주소
- TrueNAS Web UI 및 SMB 포트
- 선택적으로 부팅 완료를 확인할 추가 HTTP 서비스 포트
- 예약에 사용할 시간대

설치가 끝나면 출력된 주소를 같은 tailnet의 기기에서 엽니다.

```text
http://<이 Mac의 Tailscale IPv4>:8787
```

이 서비스는 Tailscale Serve/Funnel 설정을 만들거나 변경하지 않습니다.

## TrueNAS API 설정

켜기 기능은 API 없이 사용할 수 있지만 정상 종료, 시스템 리소스, 온도, SMB 활동 조회에는 TrueNAS API 키가 필요합니다.

1. TrueNAS Web UI에 신뢰할 수 있는 HTTPS 인증서를 구성합니다.
2. API 사용자를 만들고 필요한 권한을 부여합니다.
3. TrueNAS에서 API 키를 발급합니다.
4. Mac에서 다음을 실행합니다.

```bash
./scripts/configure-truenas.py
./scripts/install.sh
```

API 키는 macOS Keychain의 `truenas-control-web-api-key` 항목에 저장되며 설정 파일, 소스 코드 또는 로그에 기록되지 않습니다.

> TrueNAS 25.04에서는 `system.shutdown` 호출이 높은 권한을 요구할 수 있습니다. NAS 전용 API 사용자를 만들고 키를 다른 용도로 재사용하지 마세요. API 권한은 설치한 TrueNAS 버전의 공식 문서를 확인하세요.

자체 서명 인증서를 사용하면 기본 TLS 검증이 실패합니다. 가장 안전한 방법은 신뢰 가능한 인증서를 설치하는 것입니다. 불가피하게 검증을 끄려면 로컬 설정 파일의 `verify_truenas_tls`를 `false`로 변경할 수 있지만 중간자 공격 방어가 약해집니다.

## TrueNAS와 WOL 준비

1. TrueNAS에 고정 IP 또는 DHCP 예약을 설정합니다.
2. BIOS/UEFI에서 Wake-on-LAN, PCIe PME 또는 유사한 옵션을 켭니다.
3. TrueNAS 유선 인터페이스의 MAC 주소를 확인합니다.
4. ErP처럼 완전 종료 상태에서 NIC 대기전력을 끄는 옵션은 비활성화합니다.
5. TrueNAS Web UI에서 정상 종료한 뒤 같은 LAN에서 실제 WOL 부팅을 시험합니다.

첫 부팅은 몇 분 걸릴 수 있습니다. 기본값은 ping을 최대 4분 기다리고, 이후 Web UI와 SMB를 확인합니다. 추가 HTTP 서비스 포트를 설정하면 해당 서비스 준비도 기다립니다.

## 설정 변경

NAS 주소, MAC 주소, 포트 또는 시간대를 다시 입력하려면 다음을 실행한 뒤 재설치합니다.

```bash
WOL_NAS_DATA_DIR="$HOME/Library/Application Support/NAS Control" \
  ./scripts/setup.py
./scripts/install.sh
```

설정 파일은 다음 위치에 생성되며 권한은 `0600`으로 제한됩니다.

```text
~/Library/Application Support/NAS Control/config.json
```

주요 선택 항목:

| 항목 | 기본값 | 설명 |
| --- | --- | --- |
| 웹 포트 | `8787` | Tailscale IPv4에서만 수신 |
| WOL 포트 | `9`, `7` | 각 브로드캐스트 주소로 반복 전송 |
| Web UI 포트 | `80` | TrueNAS 준비 상태 확인 |
| SMB 포트 | `445` | 파일 공유 준비 상태 확인 |
| 추가 HTTP 서비스 | `0` | `0`이면 사용하지 않음 |
| 기록 보관 | `90일` | 오래된 리소스 샘플 자동 삭제 |

## 리소스 기록

NAS가 온라인이면 약 15초마다 상태를 수집하고 각 1분 안의 최고값을 SQLite에 기록합니다. 순간적으로 튄 CPU, 네트워크, 디스크 I/O 또는 온도가 마지막 샘플에 덮이지 않도록 분당 피크를 보존합니다.

ZFS는 사용하지 않는 메모리를 ARC 캐시로 적극 활용합니다. 대시보드는 전체 메모리 사용량과 ARC 사용량을 분리해 보여주므로 높은 메모리 수치가 애플리케이션의 실제 압박인지 구분할 수 있습니다.

긴 기간의 그래프는 화면 성능을 위해 구간별 평균으로 표시하지만, 최고값과 발생 시각은 원본 1분 기록으로 계산합니다. NAS가 꺼져 있을 때는 샘플을 기록하지 않습니다.

## Time Machine

TrueNAS에 별도의 Time Machine SMB 공유를 구성하면 대시보드가 열린 `*.sparsebundle` 파일을 Mac별로 묶어 백업 활동을 표시합니다.

다른 Mac을 추가하는 일반적인 방법과 보안 주의사항은 [Time Machine 설정 안내](docs/time-machine-backup.md)를 참고하세요. 이 프로젝트는 SMB 암호나 Time Machine 암호화 암호를 저장하지 않습니다.

## 서비스 관리

```bash
# 상태 확인
launchctl print gui/$(id -u)/io.github.truenas-control-web

# 재시작
launchctl kickstart -k gui/$(id -u)/io.github.truenas-control-web

# 서비스 제거 (설정과 기록은 보존)
./scripts/uninstall.sh
```

실행 코드와 데이터 위치:

```text
~/Library/Application Support/NAS Control/app
~/Library/Application Support/NAS Control/config.json
~/Library/Application Support/NAS Control/nas-control.sqlite3
~/Library/Application Support/NAS Control/nas-control.log
~/Library/Logs/truenas-control-web*.log
```

완전히 삭제하려면 먼저 제거 스크립트를 실행한 뒤 보존된 `NAS Control` 데이터 폴더를 사용자가 직접 삭제해야 합니다.

## 개발 및 테스트

외부 Python 패키지는 필요하지 않습니다.

```bash
python3 -m unittest discover -s tests -v
python3 app.py
```

개발 실행의 데이터는 프로젝트의 `data/`에 생성되며 Git에서 제외됩니다. 기본 예제 IP와 MAC은 실제 장비 정보가 아니므로 개발 실행으로 전원 동작을 시험하지 마세요.

## 보안 모델과 제한 사항

- 수신 주소는 loopback 또는 Tailscale IPv4 대역만 허용합니다.
- `0.0.0.0`, 일반 LAN IP 및 공개 IP 바인딩은 설정 검증에서 거부합니다.
- API 키는 WSS로만 전송하고 macOS Keychain에 저장합니다.
- 대시보드 자체 로그인 기능은 없습니다. 접근 제어는 Tailscale 계정과 ACL에 의존합니다.
- 같은 tailnet의 모든 기기가 접근하면 안 되는 경우 Tailscale ACL로 이 Mac의 `8787/tcp` 접근을 제한하세요.
- Wake-on-LAN은 보통 라우터나 VLAN을 넘어가지 않으므로 Mac과 NAS를 같은 LAN에 둬야 합니다.
- 스마트 플러그로 전원을 직접 끄지 마세요. ZFS 풀과 애플리케이션 데이터가 손상될 수 있습니다.

## 문제 해결

### 대시보드에 접속할 수 없음

- 설치 Mac과 접속 기기 양쪽에서 Tailscale이 연결되어 있는지 확인합니다.
- `tailscale ip -4`의 주소와 설치 시 출력된 주소가 같은지 확인합니다.
- macOS 방화벽 또는 Tailscale ACL에서 TCP `8787`이 허용되어 있는지 확인합니다.

### 켜기 실패

- NAS가 유선 LAN에 연결되어 있는지 확인합니다.
- MAC 및 브로드캐스트 주소가 정확한지 확인합니다.
- BIOS/UEFI의 WOL/PME 설정과 ErP 설정을 확인합니다.
- 먼저 같은 Mac에서 완전 종료 상태의 NAS가 WOL로 켜지는지 시험합니다.

### 끄기 또는 리소스 조회 실패

- TrueNAS HTTPS 인증서가 Mac에서 신뢰되는지 확인합니다.
- API 사용자명과 키가 유효한지 확인합니다.
- 해당 TrueNAS 버전에서 API 사용자에게 필요한 권한이 있는지 확인합니다.
- `./scripts/configure-truenas.py`를 다시 실행한 뒤 재설치합니다.

## 기여

이슈와 Pull Request를 환영합니다. 변경 전 테스트를 실행하고, 실제 IP·MAC·사용자명·API 키·로그·백업 파일 이름 같은 개인 환경 정보는 커밋하지 마세요.

## 라이선스

[Apache License 2.0](LICENSE)

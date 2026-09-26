# Windows 디스크 공간 정리 도우미
#
# 큰 용량을 차지하는 항목을 찾아 보여주고, 하나씩 물어본 뒤 지운다.
# 되돌릴 수 없는 작업은 무엇을 잃는지 먼저 알려주고 기본값을 "아니오"로 둔다.
#
# Windows PowerShell 5.1에서 돌아가야 하므로 7 전용 문법(삼항 ?:, ??)은 쓰지 않는다.

$ErrorActionPreference = "Continue"

function Get-FreeGB {
    return [math]::Round((Get-PSDrive C).Free / 1GB, 1)
}

function Get-PathGB($path) {
    if (-not (Test-Path $path)) { return 0 }
    $item = Get-Item $path -Force -ErrorAction SilentlyContinue
    if ($item -and -not $item.PSIsContainer) {
        return [math]::Round($item.Length / 1GB, 2)
    }
    $sum = (Get-ChildItem $path -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) { return 0 }
    return [math]::Round($sum / 1GB, 2)
}

function Ask($question, $defaultNo) {
    $hint = "(y/N)"
    if (-not $defaultNo) { $hint = "(Y/n)" }
    while ($true) {
        $a = Read-Host "$question $hint"
        if ($a -eq "") {
            if ($defaultNo) { return $false }
            return $true
        }
        if ($a -match '^[yY]') { return $true }
        if ($a -match '^[nN]') { return $false }
    }
}

function Write-Head($text) {
    Write-Host ""
    Write-Host ("=" * 62) -ForegroundColor DarkGray
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ("=" * 62) -ForegroundColor DarkGray
}

# ---------------------------------------------------------------- 시작
Write-Head "Windows 디스크 정리 도우미"

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "관리자 권한이 없습니다." -ForegroundColor Red
    Write-Host "disk_cleanup.bat 을 우클릭해서 '관리자 권한으로 실행'으로 다시 열어주세요."
    Read-Host "엔터를 누르면 닫힙니다"
    exit 1
}

$freeBefore = Get-FreeGB
$drive = Get-PSDrive C
$totalGB = [math]::Round(($drive.Used + $drive.Free) / 1GB, 0)
Write-Host ""
Write-Host "C 드라이브: 전체 $totalGB GB / 여유 $freeBefore GB" -ForegroundColor White

$isLaptop = $null -ne (Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
if ($isLaptop) {
    Write-Host "이 컴퓨터는 노트북으로 보입니다 (배터리 감지)." -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 조사
Write-Head "무엇이 용량을 차지하는지 확인 중 (잠시 걸립니다)"

$hiberGB = Get-PathGB "C:\hiberfil.sys"
$pageGB = Get-PathGB "C:\pagefile.sys"
$tempGB = Get-PathGB $env:TEMP
$winTempGB = Get-PathGB "C:\Windows\Temp"
$updGB = Get-PathGB "C:\Windows\SoftwareDistribution\Download"
$hasOld = Test-Path "C:\Windows.old"

Write-Host ""
Write-Host ("  {0,-34} {1,8}" -f "항목", "크기(GB)") -ForegroundColor DarkGray
Write-Host ("  {0,-34} {1,8}" -f "최대 절전 파일 (hiberfil.sys)", $hiberGB)
Write-Host ("  {0,-34} {1,8}" -f "가상 메모리 (pagefile.sys)", $pageGB)
Write-Host ("  {0,-34} {1,8}" -f "내 임시 파일", $tempGB)
Write-Host ("  {0,-34} {1,8}" -f "Windows 임시 파일", $winTempGB)
Write-Host ("  {0,-34} {1,8}" -f "받아둔 업데이트 파일", $updGB)
if ($hasOld) {
    Write-Host ("  {0,-34} {1,8}" -f "이전 Windows (Windows.old)", "20~30") -ForegroundColor Yellow
} else {
    Write-Host ("  {0,-34} {1,8}" -f "이전 Windows (Windows.old)", "없음")
}

Write-Host ""
Write-Host "복원 지점 사용량:" -ForegroundColor DarkGray
vssadmin list shadowstorage /for=C: 2>$null | Select-String "사용|Used|할당|Allocated"

# ---------------------------------------------------------------- 1. 안전
Write-Head "1단계: 안전한 정리 (되돌릴 게 없는 것들)"
Write-Host "휴지통, 임시 파일, 받아둔 업데이트 설치 파일을 지웁니다."
Write-Host "예상 확보: 약 $([math]::Round($tempGB + $winTempGB + $updGB, 1)) GB"

if (Ask "진행할까요?" $false) {
    Write-Host "  휴지통 비우는 중..." -NoNewline
    Clear-RecycleBin -DriveLetter C -Force -ErrorAction SilentlyContinue
    Write-Host " 완료"

    Write-Host "  임시 파일 지우는 중..." -NoNewline
    Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item "C:\Windows\Temp\*" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host " 완료"

    Write-Host "  받아둔 업데이트 파일 지우는 중..." -NoNewline
    Stop-Service wuauserv -Force -ErrorAction SilentlyContinue
    Remove-Item "C:\Windows\SoftwareDistribution\Download\*" -Recurse -Force -ErrorAction SilentlyContinue
    Start-Service wuauserv -ErrorAction SilentlyContinue
    Write-Host " 완료"
    Write-Host "  현재 여유: $(Get-FreeGB) GB" -ForegroundColor Green
} else {
    Write-Host "  건너뜀"
}

# ---------------------------------------------------------------- 2. 업데이트 정리
Write-Head "2단계: 오래된 Windows 업데이트 정리"
Write-Host "업데이트의 예전 버전 파일을 지웁니다. 보통 3~10 GB."
Write-Host "5~20분 걸리고, 지난 업데이트를 되돌릴 수 없게 됩니다." -ForegroundColor Yellow

if (Ask "진행할까요?" $true) {
    Write-Host "  진행 중... 창을 닫지 마세요."
    DISM /Online /Cleanup-Image /StartComponentCleanup /ResetBase
    Write-Host "  현재 여유: $(Get-FreeGB) GB" -ForegroundColor Green
} else {
    Write-Host "  건너뜀"
}

# ---------------------------------------------------------------- 3. Windows.old
if ($hasOld) {
    Write-Head "3단계: 이전 Windows 삭제 (Windows.old)"
    Write-Host "가장 크게 확보됩니다. 보통 20~30 GB."
    Write-Host "지우면 이전 버전으로 되돌릴 수 없습니다." -ForegroundColor Yellow
    Write-Host "업그레이드 후 10일이 지났다면 어차피 되돌리기가 불가능합니다."

    if (Ask "정말 지울까요?" $true) {
        Write-Host "  소유권 가져오는 중... (몇 분 걸립니다)"
        takeown /F C:\Windows.old /R /A /D Y 2>&1 | Out-Null
        icacls C:\Windows.old /grant "*S-1-5-32-544:F" /T /C 2>&1 | Out-Null
        Write-Host "  삭제하는 중..."
        Remove-Item "C:\Windows.old" -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path "C:\Windows.old") {
            Write-Host "  일부가 남았습니다. Windows 설정에서 마저 지우는 편이 확실합니다." -ForegroundColor Yellow
            Write-Host "  설정 > 시스템 > 저장소 > 임시 파일 > '이전 Windows 설치' 체크 후 제거"
        } else {
            Write-Host "  완료"
        }
        Write-Host "  현재 여유: $(Get-FreeGB) GB" -ForegroundColor Green
    } else {
        Write-Host "  건너뜀"
    }
}

# ---------------------------------------------------------------- 4. 최대 절전
if ($hiberGB -gt 0.5) {
    Write-Head "4단계: 최대 절전 모드 끄기"
    Write-Host "hiberfil.sys 를 없애 $hiberGB GB 를 확보합니다."
    if ($isLaptop) {
        Write-Host "노트북에서는 권하지 않습니다. 배터리가 떨어질 때 작업이 날아갈 수 있어요." -ForegroundColor Red
    } else {
        Write-Host "최대 절전 모드를 쓰지 않는다면 꺼도 됩니다. (빠른 시작도 함께 꺼집니다)" -ForegroundColor Yellow
    }
    Write-Host "되돌리려면 나중에 powercfg /h on 을 실행하면 됩니다."

    if (Ask "끌까요?" $true) {
        powercfg /h off
        Write-Host "  완료. 현재 여유: $(Get-FreeGB) GB" -ForegroundColor Green
    } else {
        Write-Host "  건너뜀"
    }
}

# ---------------------------------------------------------------- 5. 복원 지점
Write-Head "5단계: 시스템 복원 지점 용량 줄이기"
Write-Host "복원 지점이 쓰는 공간을 5 GB로 제한합니다. 오래된 지점은 사라집니다."
Write-Host "문제가 생겼을 때 되돌릴 수 있는 시점이 줄어듭니다." -ForegroundColor Yellow

if (Ask "진행할까요?" $true) {
    vssadmin resize shadowstorage /For=C: /On=C: /MaxSize=5GB
    Write-Host "  현재 여유: $(Get-FreeGB) GB" -ForegroundColor Green
} else {
    Write-Host "  건너뜀"
}

# ---------------------------------------------------------------- 6. faceswap
$venv = Join-Path $PSScriptRoot "..\.venv"
if (Test-Path $venv) {
    Write-Head "6단계: faceswap 앱에서 안 쓰는 라이브러리 제거"
    $venvGB = Get-PathGB $venv
    Write-Host "현재 .venv 크기: $venvGB GB"
    Write-Host "Gradio 와 yt-dlp 는 지금 앱이 쓰지 않습니다. 딸려온 것들까지 지웁니다."
    Write-Host "앱 동작에는 영향이 없습니다."

    if (Ask "진행할까요?" $false) {
        $py = Join-Path $venv "Scripts\python.exe"
        if (Test-Path $py) {
            & $py -m pip uninstall -y gradio gradio_client yt-dlp fastapi uvicorn `
                starlette pydub ffmpy python-multipart aiofiles orjson `
                semantic-version tomlkit ruff 2>&1 | Out-Null
            & $py -m pip cache purge 2>&1 | Out-Null
            Write-Host "  완료. .venv 크기: $(Get-PathGB $venv) GB" -ForegroundColor Green
        } else {
            Write-Host "  python.exe 를 찾지 못했습니다: $py" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  건너뜀"
    }
}

# ---------------------------------------------------------------- 마무리
$freeAfter = Get-FreeGB
$gained = [math]::Round($freeAfter - $freeBefore, 1)

Write-Head "정리 결과"
Write-Host "  시작 여유 공간 : $freeBefore GB"
Write-Host "  현재 여유 공간 : $freeAfter GB"
Write-Host "  확보한 공간    : $gained GB" -ForegroundColor Green
Write-Host ""
Write-Host "더 필요하다면 설정 > 시스템 > 저장소 에서 앱별 사용량을 확인해보세요."
Write-Host ""
Read-Host "엔터를 누르면 닫힙니다"

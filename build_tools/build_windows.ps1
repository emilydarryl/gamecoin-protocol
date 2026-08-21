$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Find-InnoSetupCompiler {
    # 1. PATH, if the user added Inno Setup there.
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path $cmd.Source)) {
        return $cmd.Source
    }

    # 2. Common machine-wide and per-user install locations.
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Inno Setup 6\ISCC.exe",
        "$env:USERPROFILE\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and $_ -notmatch '^\\Inno Setup' }

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }

    # 3. Registry uninstall entries. This catches winget installs that use a
    #    non-default location or a per-user installation.
    $registryRoots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )

    foreach ($root in $registryRoots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($key in (Get-ChildItem $root -ErrorAction SilentlyContinue)) {
            try {
                $item = Get-ItemProperty $key.PSPath -ErrorAction Stop
            } catch {
                continue
            }
            if ([string]$item.DisplayName -notlike 'Inno Setup*') { continue }

            if ($item.InstallLocation) {
                $candidate = Join-Path ([string]$item.InstallLocation) 'ISCC.exe'
                if (Test-Path $candidate) {
                    return (Resolve-Path $candidate).Path
                }
            }

            # Some Inno uninstall entries omit InstallLocation but include the
            # uninstaller path. ISCC.exe normally sits beside unins*.exe.
            $uninstall = [string]$item.UninstallString
            if ($uninstall) {
                $clean = $uninstall.Trim().Trim('"')
                if ($clean -match '^(.*\\)unins\d*\.exe') {
                    $candidate = Join-Path $Matches[1] 'ISCC.exe'
                    if (Test-Path $candidate) {
                        return (Resolve-Path $candidate).Path
                    }
                }
            }
        }
    }

    return $null
}

function Ensure-InnoSetupCompiler {
    $iscc = Find-InnoSetupCompiler
    if ($iscc) { return $iscc }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "Inno Setup compiler was not found in the usual locations. Asking winget to install/repair Inno Setup 6..."
        # External command output must not escape this function because the
        # caller assigns the function result to $Iscc. If winget output leaks
        # into the pipeline, PowerShell turns $Iscc into an array containing
        # both status text and the compiler path.
        & $winget.Source install --id JRSoftware.InnoSetup -e --source winget --accept-package-agreements --accept-source-agreements | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "winget failed to install Inno Setup (exit code $LASTEXITCODE)"
        }
        Start-Sleep -Seconds 2
        $iscc = Find-InnoSetupCompiler
        if ($iscc) { return $iscc }
    }

    throw @"
Inno Setup 6 is installed or required, but ISCC.exe could not be located.

Try this in Command Prompt to locate it:
  where /R "%LOCALAPPDATA%" ISCC.exe
  where /R "C:\Program Files" ISCC.exe
  where /R "C:\Program Files (x86)" ISCC.exe

Then send me the path that command reports.
"@
}

Write-Host "Building GameCoin Mainnet v1.0.0 for Windows..."
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt -r build_tools/requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }

Write-Host "Running mainnet test suite..."
py -3 -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Mainnet tests failed; refusing to build installer" }

Write-Host "Verifying fixed mainnet identity..."
py -3 -c "import node; assert node.NETWORK_NAME == 'gamecoin-mainnet'; assert node.P2P_PROTOCOL == 6; assert node.GENESIS_HASH == 'fb7282bd7a829af95ebcf32da284ab4eb2c807eb65eb6ec63aed86b9ec9a7233'; print('Verified genesis:', node.GENESIS_HASH)"
if ($LASTEXITCODE -ne 0) { throw "Mainnet identity/genesis verification failed; refusing to build installer" }

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host 'Generating branding assets from versioned SVG...'
py -3 build_tools\render_assets.py
if ($LASTEXITCODE -ne 0) { throw 'Asset generation failed.' }

$Icon = 'assets\gamecoin_protocol_mark.ico'
$AssetData = 'assets;assets'

py -3 -m PyInstaller --noconfirm --clean --onefile --icon $Icon --version-file build_tools\version_info_node.txt --name GameCoinMainnetNode node.py
py -3 -m PyInstaller --noconfirm --clean --onefile --icon $Icon --version-file build_tools\version_info_miner.txt --name GameCoinMainnetMiner miner.py
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --icon $Icon --version-file build_tools\version_info_wallet.txt --add-data $AssetData --name GameCoinMainnetWallet wallet_gui.py

$Iscc = Ensure-InnoSetupCompiler
Write-Host "Using Inno Setup compiler: $Iscc"
& $Iscc "build_tools\GameCoinInstaller.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Build complete: dist\GameCoin-Setup-v1.0.0-Mainnet.exe"

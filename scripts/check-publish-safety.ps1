<#
.SYNOPSIS
    发布前自检：确认要推到**公共仓库**的内容里没有个人信息 / 凭据 / 第三方隐私数据。

.DESCRIPTION
    背景（2026-10-09 安全审计）：本仓库是公开的展示型仓库，但历史上出现过
    内部交接文档、明文管理员口令，以及提交元数据里的私人邮箱（QQ 邮箱会随
    commit patch / .patch URL 一起公开）。本脚本把「推之前必须为真」的硬规则
    写成可执行检查：

      1. 历史里所有 author / committer 邮箱都必须是 noreply（不暴露私人邮箱）；
      2. 受版本控制的文件里不能有 .env / uploads / output / logs / backups / 证书 / dump；
      3. 受控内容里不能出现密钥、私钥、本机绝对路径（**阻断项**）；
      4. 手机号 / 身份证号 / 硬编码口令只警告（测试夹具里本来就常见假值）。

    退出码：0 = 可以推；1 = 有阻断项（不要推）。

.NOTES
    - 实现细节：`git grep` 的模式一律通过临时文件用 `-f` 传入。PowerShell 5.1 向原生
      程序传参时会吃掉参数里的双引号，含 `"` 的模式会静默失效（本脚本开发时踩过）。
    - 模式走 POSIX ERE：不要用 `\s` / `\d` / 环视，Windows 版 git 上不生效。
    - 本文件需保存为 **UTF-8 with BOM**，否则 Windows PowerShell 5.1 会按 GBK 解码中文。

.EXAMPLE
    .\scripts\check-publish-safety.ps1

.EXAMPLE
    # 覆盖允许的邮箱域名（默认 users.noreply.github.com）
    .\scripts\check-publish-safety.ps1 -AllowedEmailDomain 'users.noreply.github.com'
#>
[CmdletBinding()]
param(
    #: author/committer 邮箱允许的域名后缀（逗号分隔）
    [string]$AllowedEmailDomain = 'users.noreply.github.com',

    #: 仓库根目录（默认脚本所在仓库）
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,

    #: 跳过"历史内容"扫描（超大仓库很慢时才用；默认执行）
    [switch]$SkipHistory
)

$ErrorActionPreference = 'Stop'

# 本脚本自身含检测模式字面量，扫描内容时必须排除自己，否则永远自指命中
$script:selfExclude = ':(exclude)scripts/check-publish-safety.ps1'
$script:blocked = 0
$script:warned = 0

function Write-Block([string]$Message) {
    Write-Host "  [BLOCK] $Message" -ForegroundColor Red
    $script:blocked++
}

function Write-Warn([string]$Message) {
    Write-Host "  [warn]  $Message" -ForegroundColor Yellow
    $script:warned++
}

function Write-Ok([string]$Message) {
    Write-Host "  [ok]    $Message" -ForegroundColor Green
}

# git grep 无命中时退出码为 1，stderr 在 $ErrorActionPreference='Stop' 下会被包成
# NativeCommandError —— 统一吞掉，只返回命中行。模式走临时文件，避免引号被吃掉。
function Get-GitGrepLines {
    param(
        [Parameter(Mandatory = $true)][string]$Pattern,
        [string[]]$ExtraPathspec = @()
    )

    $patternFile = [System.IO.Path]::GetTempFileName()
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        [System.IO.File]::WriteAllText(
            $patternFile, $Pattern, (New-Object System.Text.UTF8Encoding($false)))
        $pathspec = @('--', '.', $script:selfExclude) + $ExtraPathspec
        $lines = @(git grep -n -I -E -f $patternFile $pathspec 2>$null)
        if ($LASTEXITCODE -ne 0) { return @() }
        return $lines
    }
    finally {
        $ErrorActionPreference = $previous
        Remove-Item $patternFile -Force -ErrorAction SilentlyContinue
    }
}

# `.env.example` 里的 `sk-your-deepseek-api-key` / `change-me-...` 这类占位符不该算泄露
$script:placeholderPattern = 'your[-_]|placeholder|change[-_]?me|CHANGE_ME|占位|示例|<[^>]+>'

Push-Location $RepoRoot
try {
    Write-Host '== 1) 提交者身份（author / committer 邮箱）==' -ForegroundColor Cyan
    $emails = @(git log --all --format='%ae%n%ce' | Where-Object { $_ } | Sort-Object -Unique)
    $domains = $AllowedEmailDomain.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $badEmails = @($emails | Where-Object {
            $email = $_
            -not ($domains | Where-Object { $email -like "*@$_" })
        })
    if ($badEmails.Count -gt 0) {
        foreach ($email in $badEmails) {
            Write-Block "历史里出现非 noreply 邮箱：$email（会暴露个人信息，需先做身份重写）"
        }
    }
    else {
        Write-Ok "历史里 $($emails.Count) 个身份全部是 noreply"
    }

    Write-Host '== 2) 受版本控制的路径 ==' -ForegroundColor Cyan
    $tracked = @(git ls-files)
    $forbiddenPathPattern = '(^|/)(\.env(\..+)?|uploads|output|logs|backups|node_modules|\.claude|\.trae|\.superpowers|\.verify-src|\.dsh-tmp|\.venv)(/|$)'
    # 放行：两个示例文件 + 前端 dev 用的 .env.development（只有 VITE_API_BASE_URL，无密钥）
    $allowedPathPattern = '\.env\.example$|\.env\.production\.example$|^frontend/[^/]+/\.env\.development$'
    $badPaths = @($tracked | Where-Object { $_ -match $forbiddenPathPattern -and $_ -notmatch $allowedPathPattern })
    if ($badPaths.Count -gt 0) {
        foreach ($path in $badPaths) { Write-Block "不该入库的路径被跟踪：$path" }
    }
    else {
        Write-Ok '没有 .env / uploads / output / logs / backups / 本地工具目录被跟踪'
    }

    $forbiddenExtPattern = '\.(pdf|docx|doc|xlsx|xls|csv|sql|dump|pem|key|p12|pfx|jks|keystore|db|sqlite|bak|zip|gz)$'
    $allowedExtPattern = '^scripts/init-db\.sql$'
    $badFiles = @($tracked | Where-Object { $_ -match $forbiddenExtPattern -and $_ -notmatch $allowedExtPattern })
    if ($badFiles.Count -gt 0) {
        foreach ($path in $badFiles) { Write-Block "疑似数据/证书类文件被跟踪：$path" }
    }
    else {
        Write-Ok '没有 pdf/xlsx/docx/sql/dump/证书 类文件被跟踪'
    }

    Write-Host '== 3) 受控内容里的凭据与本机路径（阻断项）==' -ForegroundColor Cyan
    $blockPatterns = @(
        'sk-[A-Za-z0-9_-]{16,}',
        'ak_[A-Za-z0-9]{16,}',
        'AKIA[0-9A-Z]{12,}',
        'ghp_[A-Za-z0-9]{20,}',
        'github_pat_[A-Za-z0-9_]{20,}',
        'glpat-[A-Za-z0-9_-]{16,}',
        '-----BEGIN [A-Z ]*PRIVATE KEY-----',
        '[A-Za-z]:\\Users\\',
        '/home/[a-z0-9_-]+/',
        '/Users/[A-Za-z0-9_.-]+/'
    )
    $blockHits = 0
    foreach ($pattern in $blockPatterns) {
        $hits = @(Get-GitGrepLines -Pattern $pattern | Where-Object { $_ -notmatch $script:placeholderPattern })
        if ($hits.Count -gt 0) {
            $blockHits += $hits.Count
            foreach ($hit in ($hits | Select-Object -First 5)) { Write-Block "命中 /$pattern/ → $hit" }
        }
    }
    if ($blockHits -eq 0) { Write-Ok '未发现密钥 / 私钥 / 本机绝对路径' }

    Write-Host '== 4) 手机号 / 身份证号 / 硬编码口令（仅警告）==' -ForegroundColor Cyan
    $warnPatterns = @(
        '(^|[^0-9])1[3-9][0-9]{9}([^0-9]|$)',
        '(^|[^0-9])[0-9]{17}[0-9Xx]([^0-9]|$)',
        # 就是这一类的写法在 2026-10-09 把管理员口令泄到了公共仓库上
        '(password|passwd|pwd|secret|token|api_key|apikey)[^=]{0,20}[=:][[:space:]]*["''][^"'']{8,}["'']'
    )
    foreach ($pattern in $warnPatterns) {
        # 测试夹具里本来就满是假口令，只对非测试代码报"硬编码口令"
        $extra = @(':(exclude)backend/tests/**', ':(exclude)backend/scripts/smoke_*.py')
        $hits = @(Get-GitGrepLines -Pattern $pattern -ExtraPathspec $extra |
                Where-Object { $_ -notmatch $script:placeholderPattern })
        if ($hits.Count -gt 0) {
            Write-Warn "命中 /$pattern/ 共 $($hits.Count) 处（确认不是真实口令/真实号码即可）：$($hits[0])"
        }
    }

    Write-Host '== 5) 危险文件类型是否曾经进过历史 ==' -ForegroundColor Cyan
    $everAdded = @(git log --all --pretty=format: --name-only --diff-filter=A |
            Where-Object { $_ } | Sort-Object -Unique |
            Where-Object { $_ -match $forbiddenExtPattern -and $_ -notmatch $allowedExtPattern })
    if ($everAdded.Count -gt 0) {
        foreach ($path in $everAdded) { Write-Block "历史里曾经提交过：$path（即使后来删了，公共仓库仍可能按 SHA 读到）" }
    }
    else {
        Write-Ok '历史里从未出现过 pdf/xlsx/docx/dump/证书 类文件'
    }

    Write-Host '== 6) 历史**内容**里的凭据（阻断项，-SkipHistory 可跳过）==' -ForegroundColor Cyan
    # 为什么必须有这一节：2026-10-09 实测踩到过 —— 只重写 author/committer 元数据
    # 是不够的，旧提交**文件内容**里的口令仍能通过 `git log -p` / 网页 diff 看到。
    if ($SkipHistory) {
        Write-Warn '已按 -SkipHistory 跳过历史内容扫描'
    }
    else {
        $historyDiff = @(git log --all -p --pretty=format: 2>$null)
        $historyHits = 0
        foreach ($pattern in $blockPatterns) {
            $hits = @($historyDiff | Select-String -Pattern $pattern |
                    Where-Object { $_.Line -notmatch $script:placeholderPattern })
            if ($hits.Count -gt 0) {
                $historyHits += $hits.Count
                $sample = $hits[0].Line.Trim()
                if ($sample.Length -gt 120) { $sample = $sample.Substring(0, 120) }
                Write-Block "历史内容命中 /$pattern/ 共 $($hits.Count) 处：$sample"
            }
        }
        if ($historyHits -eq 0) {
            Write-Ok "全部 $((git rev-list --all --count)) 个提交的历史内容里没有密钥 / 私钥 / 本机路径"
        }
    }
}
finally {
    Pop-Location
}

Write-Host ''
if ($blocked -gt 0) {
    Write-Host "结论：有 $blocked 个阻断项、$warned 个警告 —— 不要推送。" -ForegroundColor Red
    exit 1
}

Write-Host "结论：无阻断项（$warned 个警告）—— 可以推送。" -ForegroundColor Green
exit 0

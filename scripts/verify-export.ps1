<#
.SYNOPSIS
    从 git HEAD 导出「只含已提交代码」的 backend/ 到 .verify-src/，供干净验收栈使用。

.DESCRIPTION
    为什么需要它：dev 后端（career_backend）是 `./backend` bind mount + `--reload`，
    工作区里**他人未提交的改动**也会被一起跑起来 → 那时做的"线上验收"其实是在混合态
    运行时里做的，证据不干净（2026-09-25 发现，见计划文件 §2.9 之后的讨论）。

    本脚本导出一棵**孤立的、等于 git HEAD 的** backend 源码树；再用
    `docker-compose.verify.yml` 起 verify-backend（容器名 career_backend_verify，
    宿主端口 8012，**无 --reload**），于是验收对象是冻结的已提交代码。

.PARAMETER IncludeDirty
    可选：把工作区里这些路径的**当前内容**叠加进验收栈（用于验证自己还没提交的改动）。
    路径相对仓库根，例如：
        pwsh scripts/verify-export.ps1 -IncludeDirty backend/app/api/v1/chat.py,backend/app/core/agent/nodes.py
    不传 = 纯 HEAD。

.PARAMETER Dest
    导出目录（默认 .verify-src，已被 .gitignore 忽略）。

.EXAMPLE
    pwsh scripts/verify-export.ps1
    docker compose -f docker-compose.yml -f docker-compose.verify.yml up -d verify-backend
    curl.exe -s http://localhost:8012/api/v1/admin/system/routes
    docker compose -f docker-compose.yml -f docker-compose.verify.yml rm -sf verify-backend
#>
param(
    [string[]]$IncludeDirty = @(),
    [string]$Dest = ".verify-src"
)

$ErrorActionPreference = "Stop"

$root = (git rev-parse --show-toplevel).Trim()
if (-not $root) { throw "不在 git 仓库里" }

$destPath = Join-Path $root $Dest
$tarPath = Join-Path $root "${Dest}.tar"

Write-Host "[1/4] 导出 git HEAD 的 backend/ → $Dest"
if (Test-Path $destPath) { Remove-Item $destPath -Recurse -Force }
New-Item -ItemType Directory -Force -Path $destPath | Out-Null
# 用 --output 落地成文件再解包：PowerShell 管道是按文本处理的，二进制 tar 直接管道会损坏
git -C $root archive --format=tar -o $tarPath HEAD backend
if ($LASTEXITCODE -ne 0) { throw "git archive 失败（exit=$LASTEXITCODE）" }
tar -xf $tarPath -C $destPath
if ($LASTEXITCODE -ne 0) { throw "tar 解包失败（exit=$LASTEXITCODE）" }
Remove-Item $tarPath -Force
Write-Host "      HEAD = $(git -C $root rev-parse --short HEAD)"

if ($IncludeDirty.Count -gt 0) {
    Write-Host "[2/4] 叠加工作区改动（未提交，仅这些路径）"
    foreach ($rel in $IncludeDirty) {
        $src = Join-Path $root $rel
        if (-not (Test-Path $src)) { throw "找不到工作区文件：$rel" }
        $dst = Join-Path $destPath $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Copy-Item $src $dst -Force
        Write-Host "      + $rel"
    }
} else {
    Write-Host "[2/4] 未叠加工作区改动（纯 HEAD）"
}

Write-Host "[3/4] 复制本地 backend/.env（与 dev 栈配置对齐；.env 已被 gitignore，不会入库）"
$envFile = Join-Path $root "backend/.env"
if (Test-Path $envFile) {
    Copy-Item $envFile (Join-Path $destPath "backend/.env") -Force
} else {
    Write-Host "      警告：backend/.env 不存在，验收栈将使用代码默认配置"
}

Write-Host "[4/4] 完成。下一步："
Write-Host "      docker compose -f docker-compose.yml -f docker-compose.verify.yml up -d verify-backend"
Write-Host "      # 验收：http://localhost:8012  （dev 栈仍是 8002 / nginx 80）"
Write-Host "      # 收工：docker compose -f docker-compose.yml -f docker-compose.verify.yml rm -sf verify-backend"

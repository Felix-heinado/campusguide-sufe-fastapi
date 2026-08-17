$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot ".env"
$examplePath = Join-Path $projectRoot ".env.example"
$indexPath = Join-Path $projectRoot "data\vector_index.json"

function Set-EnvValue {
    param(
        [string]$Content,
        [string]$Name,
        [string]$Value
    )

    $line = "$Name=$Value"
    $pattern = "(?m)^" + [regex]::Escape($Name) + "=.*$"
    if ([regex]::IsMatch($Content, $pattern)) {
        return [regex]::Replace($Content, $pattern, $line)
    }
    return $Content.TrimEnd() + [Environment]::NewLine + $line + [Environment]::NewLine
}

Write-Host "将开启硅基流动 Qwen/Qwen3-Embedding-4B 混合检索。" -ForegroundColor Cyan
Write-Host "API Key 仅写入本机 .env（该文件已被 Git 忽略），输入时不会显示。"
$secureKey = Read-Host "请粘贴 SILICONFLOW_API_KEY" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}

if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "API Key 不能为空。"
}

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $examplePath -Destination $envPath
}

$content = Get-Content -LiteralPath $envPath -Raw
$content = Set-EnvValue $content "RAG_ENABLE_SEMANTIC_SEARCH" "true"
$content = Set-EnvValue $content "SILICONFLOW_API_KEY" $apiKey
$content = Set-EnvValue $content "SILICONFLOW_BASE_URL" "https://api.siliconflow.cn/v1"
$content = Set-EnvValue $content "SILICONFLOW_EMBEDDING_MODEL" "Qwen/Qwen3-Embedding-4B"
[IO.File]::WriteAllText($envPath, $content, [Text.UTF8Encoding]::new($false))

# The current process does not reload .env automatically, so expose the same
# values while building the index. Future backend processes read them from .env.
$env:RAG_ENABLE_SEMANTIC_SEARCH = "true"
$env:SILICONFLOW_API_KEY = $apiKey
$env:SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
$env:SILICONFLOW_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"

Push-Location $projectRoot
try {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if ($uv) {
        & $uv.Source run --no-sync python -m app.build_vector_index
    }
    elseif (Test-Path -LiteralPath $venvPython) {
        & $venvPython -m app.build_vector_index
    }
    else {
        & python -m app.build_vector_index
    }
    if ($LASTEXITCODE -ne 0) {
        throw "向量索引生成失败，退出码：$LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $indexPath)) {
    throw "未找到生成后的 data/vector_index.json。"
}

$index = Get-Content -LiteralPath $indexPath -Raw | ConvertFrom-Json
Write-Host "完成：$($index.documentCount) 份资料已生成向量索引。" -ForegroundColor Green
Write-Host "模型：$($index.model)；维度：$($index.dimensions)"
Write-Host "现在重启后端，查询结果中的 retrieval.mode 应显示 hybrid。"

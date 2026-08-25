# Quick Setup Script for FinRAG with LlamaParse

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "FinRAG + LlamaParse Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if OpenAI API key is set
$openai_key = $env:OPENAI_API_KEY
if (-not $openai_key) {
    Write-Host "⚠️  OPENAI_API_KEY not set" -ForegroundColor Yellow
    Write-Host ""
    $input_key = Read-Host "Enter your OpenAI API key (or press Enter to skip)"
    if ($input_key) {
        $env:OPENAI_API_KEY = $input_key
        Write-Host "✅ OpenAI API key set for this session" -ForegroundColor Green
    }
} else {
    Write-Host "✅ OPENAI_API_KEY already set" -ForegroundColor Green
}

Write-Host ""

# Check if LlamaParse API key is set
$llama_key = $env:LLAMA_CLOUD_API_KEY
if (-not $llama_key) {
    Write-Host "⚠️  LLAMA_CLOUD_API_KEY not set (optional but recommended)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "LlamaParse provides superior PDF parsing for financial documents." -ForegroundColor White
    Write-Host "It preserves tables, layouts, and complex structures." -ForegroundColor White
    Write-Host ""
    Write-Host "Get your free API key at: https://cloud.llamaindex.ai/" -ForegroundColor Cyan
    Write-Host "Free tier: 1,000 pages/day" -ForegroundColor White
    Write-Host ""
    $input_key = Read-Host "Enter your LlamaParse API key (or press Enter to skip)"
    if ($input_key) {
        $env:LLAMA_CLOUD_API_KEY = $input_key
        Write-Host "✅ LlamaParse API key set for this session" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Will use PyPDF2 fallback (basic parsing)" -ForegroundColor Yellow
    }
} else {
    Write-Host "✅ LLAMA_CLOUD_API_KEY already set" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Installing Dependencies" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Install requirements
pip install -r requirements.txt

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Testing Installation" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Run tests
python test_installation.py

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Run example:    python example.py" -ForegroundColor Cyan
Write-Host "  2. Interactive:    python cli.py" -ForegroundColor Cyan
Write-Host "  3. With your PDF:  python main.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "For more info:" -ForegroundColor White
Write-Host "  • Getting Started: GETTING_STARTED.md" -ForegroundColor Cyan
Write-Host "  • LlamaParse Guide: LLAMAPARSE.md" -ForegroundColor Cyan
Write-Host "  • Full Docs: README.md" -ForegroundColor Cyan
Write-Host ""

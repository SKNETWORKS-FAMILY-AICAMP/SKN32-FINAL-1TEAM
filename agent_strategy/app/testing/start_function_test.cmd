@echo off
cd /d "%~dp0\..\..\.."
powershell -NoProfile -Command "$strategyApiKey=[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','User'); if (-not $strategyApiKey) { $strategyApiKey=[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','Machine') }; if ($strategyApiKey) { $env:OPENAI_API_KEY=$strategyApiKey }; $env:SBRAIN_AUTO_RESEARCH='1'; python -B -m agent_strategy.app.testing.test_server --port 8765"
pause

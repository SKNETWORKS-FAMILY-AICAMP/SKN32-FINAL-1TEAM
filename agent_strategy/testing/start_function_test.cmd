@echo off
cd /d "%~dp0\..\.."
powershell -NoProfile -Command "$strategyApiKey=[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','User'); if (-not $strategyApiKey) { $strategyApiKey=[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','Machine') }; if ($strategyApiKey) { $env:OPENAI_API_KEY=$strategyApiKey }; python -B -m agent_strategy.testing.test_server --port 8765"
pause

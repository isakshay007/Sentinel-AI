from backend.llm import quick_prompt

response = quick_prompt(
    prompt="You are a DevOps AI. Analyze this: CPU usage at 95% for 10 minutes, 3 OOM kills in logs. What's happening?",
    system="You are SentinelAI, an expert DevOps incident responder. Be concise."
)
print(response)
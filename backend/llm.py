from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

def get_llm(model: str = "llama3.1:8b", temperature: float = 0.1):
    return ChatOllama(
        model=model,
        temperature=temperature,
        base_url="http://localhost:11434"
    )

def quick_prompt(prompt: str, system: str = None, model: str = "llama3.1:8b") -> str:
    llm = get_llm(model)
    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))
    response = llm.invoke(messages)
    return response.content
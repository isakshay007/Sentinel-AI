from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

load_dotenv()

def get_llm(model: str = "llama-3.1-8b-instant", temperature: float = 0.1):
    return ChatGroq(
        model=model,
        temperature=temperature,
    )

def quick_prompt(prompt: str, system: str = None, model: str = "llama-3.1-8b-instant") -> str:
    llm = get_llm(model)
    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))
    response = llm.invoke(messages)
    return response.content
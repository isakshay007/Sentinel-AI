from langchain_core.prompts import ChatPromptTemplate
from backend.llm import get_llm

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a DevOps incident analyst. Respond in JSON format."),
    ("human", "Classify this incident: {description}")
])

chain = prompt | get_llm()
result = chain.invoke({"description": "API response times jumped from 200ms to 5000ms after deploy v2.3.1"})
print(result.content)
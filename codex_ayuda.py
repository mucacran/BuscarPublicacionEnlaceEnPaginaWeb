import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

response = client.chat.completions.create(
    model="gpt-4o",  # o usa "gpt-3.5-turbo" si no tienes acceso a gpt-4o
    messages=[
        {"role": "system", "content": "Eres un experto programador en Python."},
        {"role": "user", "content": "Escribe una función en Python que reciba HTML y devuelva todos los enlaces <a href='...'> como lista"}
    ],
    temperature=0,
)

print("✅ Codex (GPT) respondió con esta función:\n")
print(response.choices[0].message.content)

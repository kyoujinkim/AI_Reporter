# this is a tool for managing agents
from openai import OpenAI

# define the agent class
class Agent:
    def __init__(self, api_key, name,description, model="gpt-4.1-nano-2025-04-14", tools=None):
        self.name = name
        self.model = model
        self.description = description
        self.messages = [{"role": "system", "content": self.description}]
        self.tools = tools if tools is not None else []
        self.client = OpenAI(api_key=api_key)

    def run(self, prompt, max_tokens=1000, temperature=0.7):
        self.messages.append({"role": "system", "content": prompt})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            #max_tokens=max_tokens,
            temperature=temperature
        )
        self.messages.append(response.choices[0].message)

        return response.choices[0].message.content

    def add_tool(self, tool):
        self.tools.append(tool)

    def remove_tool(self, tool_name):
        self.tools = [tool for tool in self.tools if tool.name != tool_name]

    def get_tool(self, tool_name):
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        return None

    def list_tools(self):
        return [tool.name for tool in self.tools]

    def __repr__(self):
        return f"Agent(name={self.name}, description={self.description}, tools={self.list_tools()})"
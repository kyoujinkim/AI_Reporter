# this is a tool for managing agents
from openai import OpenAI, BadRequestError
import httpx
http_client = httpx.Client(verify=False)

# define the agent class
class Agent:
    def __init__(self, api_key, name,description, model="gpt-4.1-nano-2025-04-14", tools=None):
        self.name = name
        self.model = model
        self.description = description
        self.messages = [{"role": "system", "content": self.description}]
        self.tools = tools if tools is not None else []
        self.client = OpenAI(api_key=api_key, http_client=http_client)

    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content})

    # inherit message from other agents
    def inherit_messages(self, other_agent):
        self.messages.extend(other_agent.messages)

    def run(self, prompt, temperature=0.7):
        self.messages.append({"role": "system", "content": prompt})
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=self.tools,
                temperature=temperature
            )
        except BadRequestError:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=self.tools
            )
        self.messages.append(response.choices[0].message)

        return response.choices[0].message.content

    def run_with_structured_format(self, prompt, response_format, temperature=0.7):
        self.messages.append({"role": "system", "content": prompt})
        try:
            response = self.client.responses.parse(
            model=self.model,
            input=self.messages,
            temperature=temperature,
            tools=self.tools,
            text_format=response_format
            )
        except BadRequestError:
            response = self.client.responses.parse(
            model=self.model,
            input=self.messages,
            tools=self.tools,
            text_format=response_format
            )

        return response.output_parsed

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
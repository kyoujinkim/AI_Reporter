from src.tools.agents import Agent
from langchain_core.tools import tool

class HumanEditor:
    def __init__(self, openai_key, model='gpt-4.1-mini', tools=None):
        self.editagent = Agent(
            api_key=openai_key,
            name="EditorAgent",
            description="당신은 입력받은 수정 요구를 반영하여 텍스트를 수정하는 전문가입니다.",
            model=model,
            tools=tools
        )

    def run(self, text):
        # confirm final report with human interruption
        print(f"\n분석 결과:\n{text}...\n\n")
        print("분석이 완료되었습니다. 내용을 확인하고 잘못된 부분에 대해 수정할 부분을 입력하세요. 없으면 엔터를 누르세요.")
        while True:
            user_input = input("수정할 부분이 있으면 입력하세요 (종료하려면 'exit' 입력): ")
            if user_input.lower() == 'exit':
                break
            elif user_input.strip() == '':
                print("수정 없이 종료합니다.")
                break
            else:
                self.editagent.add_message(role="user", content=text)
                text = self.editagent.run(
                    prompt=f"문서에서 다음의 수정 요구를 반영하여 수정해 주세요.\n\n수정 요구: {user_input}"
                )
                print(f"\n수정 결과:\n{text}\n")
                self.editagent.add_message(role="assistant", content=text)

        return text

    @tool
    def read_company_business(self) -> str:
        """회사 사업보고서 내용을 읽고 요약하는 툴"""
        print(f"... 회사 사업보고서 읽기 ...\n")
        # 회사 사업보고서 읽기 로직 구현
        # read data/{code}_summary/company_business.md
        result = ""
        with open(f"data/{self.code}_summary/company_business.md", "r", encoding="utf-8") as f:
            result = f.read()

        return result

    @tool
    def read_financial_analysis(self) -> str:
        """재무분석 내용을 읽고 요약하는 툴"""
        print(f"... 재무분석 읽기 ...\n")
        # 재무분석 읽기 로직 구현
        # read data/{code}_summary/financial_analysis.md
        result = ""
        with open(f"data/{self.code}_summary/financial_analysis.md", "r", encoding="utf-8") as f:
            result = f.read()

        return result

    @tool
    def read_earnings_analysis(self) -> str:
        """실적분석 내용을 읽고 요약하는 툴"""
        print(f"... 실적분석 읽기 ...\n")
        # 실적분석 읽기 로직 구현
        # read data/{code}_summary/earnings_analysis.md
        result = ""
        with open(f"data/{self.code}_summary/earnings_analysis.md", "r", encoding="utf-8") as f:
            result = f.read()

        return result

    @tool
    def read_consensus_analysis(self) -> str:
        """미래가이던스분석 내용을 읽고 요약하는 툴"""
        print(f"... 미래가이던스분석 읽기 ...\n")
        # 미래가이던스분석 읽기 로직 구현
        # read data/{code}_summary/future_guidance_analysis.md
        result = ""
        with open(f"data/{self.code}_summary/consensus_analysis.md", "r", encoding="utf-8") as f:
            result = f.read()

        return result

    @tool
    def read_ir_summary(self) -> str:
        """IR요약 내용을 읽고 요약하는 툴"""
        print(f"... IR요약 읽기 ...\n")
        # IR요약 읽기 로직 구현
        # read data/{code}_summary/ir_summary.md
        result = ""
        with open(f"data/{self.code}_summary/ir_summary.md", "r", encoding="utf-8") as f:
            result = f.read()

        return result

    @tool
    def read_news_analysis(self) -> str:
        """뉴스분석 내용을 읽고 요약하는 툴"""
        print(f"... 뉴스분석 읽기 ...\n")
        # 뉴스분석 읽기 로직 구현
        # read data/{code}_summary/news_analysis.md
        result = ""
        with open(f"data/{self.code}_summary/news_analysis.md", "r", encoding="utf-8") as f:
            result = f.read()

        return result
from src.tools.agents import Agent
from langchain_core.tools import tool

class HumanEditor:
    def __init__(self, openai_key, model='gpt-4.1-mini', tools=None):
        self.editagent = Agent(
            api_key=openai_key,
            name="EditorAgent",
            description="당신은 문서를 편집하는 전문가입니다. 사용자의 수정 요구를 반영하여 기존에 작성되었던 문서를 수정합니다.",
            model=model,
            tools=tools
        )

    def run(self, text):
        # confirm final report with human interruption
        print(f"\n분석 결과:\n{text}...\n\n")
        print("""분석이 완료되었습니다. 내용을 확인하고 잘못된 부분에 대해 수정할 부분을 입력하세요.\n
만약 수정된 내용을 중간 저장하려면 'save'를 입력하세요.\n
최근 수정 내용을 롤백해서 제거하고, 중간에 저장한 결과물까지 돌아가려면 'rollback'을 입력하세요.\n
수정이 완료되었으면 'exit'를 입력하세요. 'save'로 저장한 text가 최종 결과물이 됩니다.
        """)
        self.editagent.add_message(role="system", content='[작성 문서]\n\n' + text)
        while True:
            user_input = input("입력 : ")
            if user_input.lower() == 'exit' or user_input.strip() == '':
                print("종료합니다.")
                break
            elif user_input.lower() == 'save':
                print("중간 저장했습니다.")
                self.editagent.add_message(role="system", content='[작성 문서]\n\n' + text)
            elif user_input.lower() == 'rollback':
                # find recent [작성 문서] message and remove it
                for i in range(len(self.editagent.messages)-1, -1, -1):
                    if "[작성 문서]" in self.editagent.messages[i]['content']:
                        print("최근 수정 내용을 롤백했습니다.")
                        break
                    else:
                        removed_message = self.editagent.messages.pop(i)
                        print(f"롤백된 메시지: {removed_message}")
            else:
                text = self.editagent.run(
                    prompt=f"작성 문서에서 다음의 요청를 반영해 주세요.\n\n요청: {user_input}"
                )
                print(f"\n수정 결과:\n{text}\n")

        for i in range(len(self.editagent.messages) - 1, -1, -1):
            if "[작성 문서]" in self.editagent.messages[i]['content']:
                return self.editagent.messages[i]['content'].replace('[작성 문서]\n\n', '')


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
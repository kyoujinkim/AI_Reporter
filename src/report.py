import configparser

from src.tools.business_analyst import BusinessAnalyst
from src.tools.news_analyst import NewsAnalyst
from src.tools.financial_analyst import FinancialAnalyst
from src.tools.earnings_analyst import EarningsAnalyst
from src.tools.consensus_analyst import ConsensusAnalyst
from src.tools.ir_analyst import IrAnalyst

import OpenDartReader

# turn off warnings
import warnings
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    config_file = "D:/config.ini"
    config = configparser.ConfigParser()
    config.read(config_file)
    dart_key = config.get("dart", "API_KEY")
    ai_key = config.get("openai", "API_KEY")
    tavily_api_key = config.get("tavily", "API_KEY_NH")

    dart = OpenDartReader(dart_key)

    code = '046890'
    industry = "LED 반도체 제조업"

    # 회사 기본정보 조회
    company_info = dart.company(code)
    company_info['industry'] = industry

    # Read annual report and summarize
    business_analyst = BusinessAnalyst(openai_key=ai_key, dart_key=dart_key)
    company_business = business_analyst.run(company_info)
    #print(company_business.summary)

    # Read financial data and analyze
    financial_analyst = FinancialAnalyst(openai_key=ai_key)
    financial_analysis = financial_analyst.run(company_info)
    #print(financial_analysis)

    # Read earnings report
    earnings_analyst = EarningsAnalyst(openai_key=ai_key, dart_key=dart_key)
    earnings_analysis = earnings_analyst.run(company_info)
    #print(earnings_analysis)

    # Read and analyzre future guidance data
    consensus_analyst = ConsensusAnalyst(openai_key=ai_key)
    future_guidance_analysis = consensus_analyst.run(company_info)
    #print(future_guidance_analysis)

    # Read IR report
    ir_analyst = IrAnalyst(openai_key=ai_key)
    ir_summary = ir_analyst.run(company_info)
    #print(ir_summary.summary)

    # Search News from Tavily
    news_analyst = NewsAnalyst(openai_key=ai_key, tavily_key=tavily_api_key)
    news_analysis = news_analyst.run(company_info)
    #print(news_analysis)
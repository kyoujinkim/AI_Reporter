import configparser
import time

from src.ai_reporter import AIReporter
from src.tools.business_analyst import BusinessAnalyst
from src.tools.news_analyst import NewsAnalyst
from src.tools.financial_analyst import FinancialAnalyst
from src.tools.earnings_analyst import EarningsAnalyst
from src.tools.consensus_analyst import ConsensusAnalyst
from src.tools.estimate_analyst import EstimateAnalyst
from src.tools.ir_analyst import IrAnalyst

import OpenDartReader

# turn off warnings
import warnings
warnings.filterwarnings("ignore")
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

config_file = "D:/config.ini"
config = configparser.ConfigParser()
config.read(config_file)
dart_key = config.get("dart", "API_KEY")
ai_key = config.get("openai", "API_KEY")
tavily_api_key = config.get("tavily", "API_KEY_NH")

if __name__ == "__main__":

    code = '237690'
    industry = "신약 개발 위탁 서비스"

    # print time info and calculate time spent
    start_time = time.time()
    print(f"Start Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")

    # 회사 기본정보 조회
    dart = OpenDartReader(dart_key)
    company_info = dart.company(code)
    company_info['industry'] = industry

    # Read annual report and summarize
    business_analyst = BusinessAnalyst(openai_key=ai_key, dart_key=dart_key)
    #company_business = business_analyst.run(company_info)

    # Read financial data and analyze
    financial_analyst = FinancialAnalyst(openai_key=ai_key)
    #financial_analysis = financial_analyst.run(company_info)

    # Read earnings report
    earnings_analyst = EarningsAnalyst(openai_key=ai_key, dart_key=dart_key)
    #earnings_analysis = earnings_analyst.run(company_info)

    # Read and analyzre future guidance data
    consensus_analyst = ConsensusAnalyst(openai_key=ai_key)
    #future_guidance_analysis = consensus_analyst.run(company_info)

    # Read IR report
    ir_analyst = IrAnalyst(openai_key=ai_key)
    #ir_summary = ir_analyst.run(company_info)

    # Search News from Tavily
    news_analyst = NewsAnalyst(openai_key=ai_key, tavily_key=tavily_api_key)
    news_analysis = news_analyst.run(company_info)

    # Read and Estimate next quarter earnings
    estimate_analyst = EstimateAnalyst(openai_key=ai_key)
    earnings_estimation = estimate_analyst.run(company_info)

    # Generate AI Report
    reporter = AIReporter(code)
    reporter.run()

    # print total time spent
    end_time = time.time()
    print(f"End Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
    print(f"Total Time Spent: {end_time - start_time:.2f} seconds")
import argparse
import configparser
import time
from glob import glob
import os

from src.ai_reporter import AIReporter
from src.tools.business_analyst import BusinessAnalyst
from src.tools.news_analyst import NewsAnalyst
from src.tools.financial_analyst import FinancialAnalyst
from src.tools.earnings_analyst import EarningsAnalyst
from src.tools.consensus_analyst import ConsensusAnalyst
from src.tools.estimate_analyst import EstimateAnalyst
from src.tools.ir_analyst import IrAnalyst
from src.md_to_pptx_converter import MDToPPTXConverter

import OpenDartReader

# turn off warnings
import warnings

warnings.filterwarnings("ignore")
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def convert_md_to_txt(md_file, txt_file):
    with open(md_file, 'r', encoding='utf-8') as mdf, open(txt_file, 'w', encoding='utf-8') as txtf:
        for line in mdf:
            # Remove markdown syntax for simplicity
            line = line.replace('#', '').replace('*', '').replace('`', '')
            txtf.write(line)

config_file = "D:/config.ini"
config = configparser.ConfigParser()
config.read(config_file)
dart_key = config.get("dart", "API_KEY")
ai_key = config.get("openai", "API_KEY")
tavily_api_key = config.get("tavily", "API_KEY_NH")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate AI Report for a company.')
    parser.add_argument('--code', type=str, help='Company code (e.g., 418470 for Yoonjae)')
    parser.add_argument('--industry', type=str, help='Industry of the company (e.g., 전자책 정기구독 서비스)')
    args = parser.parse_args()

    code = args.code #'418470'
    industry = args.industry #"전자책 정기구독 서비스"
    code = '012510'
    industry = "전자책 정기구독 서비스"

    # print time info and calculate time spent
    start_time = time.time()
    print(f"Start Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")

    # 회사 기본정보 조회
    dart = OpenDartReader(dart_key)
    company_info = dart.company(code)
    name = company_info['stock_name']
    market_code = company_info['corp_cls']
    if market_code == "Y":
        market = "KS"
    elif market_code == "K":
        market = "KQ"
    else:
        market = "KS"
    company_info['industry'] = industry

    # Read annual report and summarize
    business_analyst = BusinessAnalyst(openai_key=ai_key, dart_key=dart_key)
    company_business = business_analyst.run(company_info)

    # Read financial data and analyze
    financial_analyst = FinancialAnalyst(openai_key=ai_key)
    financial_analysis = financial_analyst.run(company_info)

    # Read earnings report
    earnings_analyst = EarningsAnalyst(openai_key=ai_key, dart_key=dart_key)
    earnings_analysis = earnings_analyst.run(company_info)

    # Read and analyzre future guidance data
    consensus_analyst = ConsensusAnalyst(openai_key=ai_key)
    future_guidance_analysis = consensus_analyst.run(company_info)

    # Read IR report
    ir_analyst = IrAnalyst(openai_key=ai_key)
    ir_summary = ir_analyst.run(company_info)

    # Search News from Tavily
    news_analyst = NewsAnalyst(openai_key=ai_key, tavily_key=tavily_api_key)
    news_analysis = news_analyst.run(company_info)

    # Read and Estimate next quarter earnings
    estimate_analyst = EstimateAnalyst(openai_key=ai_key)
    earnings_estimation = estimate_analyst.run(company_info)

    # Generate AI Report
    reporter = AIReporter(code, name, market, model='gpt-5.2-2025-12-11')
    report_path = reporter.run()

    # Convert md into txt for human reading
    md_list = glob(f"./data/A{code}_summary/*.md")
    # create folder for txt files
    txt_folder = f"./output/A{code}"
    if not os.path.exists(txt_folder):
        os.makedirs(txt_folder)
    for md_file in md_list:
        txt_file = txt_folder + '/' + md_file.split('\\')[-1].replace('.md', '.txt')
        convert_md_to_txt(md_file, txt_file)

    converter = MDToPPTXConverter('data/config/template.pptx')
    a = converter.convert(report_path
                          , report_path.replace('.md', '.pptx'))

    # print total time spent
    end_time = time.time()
    print(f"End Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
    print(f"Total Time Spent: {end_time - start_time:.2f} seconds")
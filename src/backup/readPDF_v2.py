import warnings

from tqdm import tqdm

import os, re
from glob import glob
from typing import List

from langchain_core.documents import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from unstructured.partition.pdf import partition_pdf

from tqdm.contrib.concurrent import process_map

class PDFReader:
    def __init__(self):
        '''
        PDF 문서를 읽어서 텍스트를 추출하는 클래스입니다.
        '''

    @staticmethod
    def cleanse_text(text):
        nonNameList = "[.<>?:|/\\*]"
        EMAIL_PATTERN = re.compile(r'''(([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+)(\.[a-zA-Z]{2,4}))''')
        URL_PATTERN = re.compile(r"(ftp|http|https)?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
        URL_PATTERN2 = re.compile(r"www.(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
        ACCOUNT_PATTERN = re.compile(r'@[a-zA-Z]*')
        PHONE_PATTERN = re.compile(r'(\))?\d{2,3}( )?(\)| |-|\.)?( )?\d{3,4}( )?( |-|\.)?( )?\d{4}')
        removal_list = "_#@|◇·△▲▷▶➤●■□○>>-∼=ㆍ<>【】…◆"
        MULTIPLE_SPACES = re.compile(' +', re.UNICODE)

        text = re.sub(EMAIL_PATTERN, ' ', text)   # 이메일 패턴 제거
        text = re.sub(URL_PATTERN, ' ', text)   # URL 패턴 제거
        text = re.sub(URL_PATTERN2, ' ', text)   # URL 패턴 제거
        text = re.sub(ACCOUNT_PATTERN, ' ', text)   # 트위터 계정명 패턴 제거 (e.g., @iAmPanoramic)
        text = re.sub(PHONE_PATTERN, ' ', text)

        return text

    @staticmethod
    def retrieve_table(elements:list):
        '''
        PDF 문서에서 표를 추출하는 함수입니다.
        표는 Table 요소와 Title 혹은 FiguireCaption 요소로 구성되어 있습니다.
        :param elements: PDF 문서의 요소들
        :return:
        '''
        tables = []
        tableidx = []
        for idx in range(len(elements)):
            if elements[idx].category == 'Table':
                tableidx.append(idx)
                tabletext = ''
                tabletext += elements[idx].text
                # 표의 제목을 찾기 위해 이전 요소들을 확인
                tabletitle = ''
                for recursive_idx in range(idx-2, idx):
                    if elements[recursive_idx].category in ['Title', 'FigureCaption']:
                        tabletitle += '\n' + elements[recursive_idx].text
                        tableidx.append(recursive_idx)
                tabletext = tabletitle + '\n\n' + tabletext

                tables.append(tabletext)

        return tables, tableidx

    @staticmethod
    def fun_partion_pdf(filename):
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*CropBox.*")
                elements = partition_pdf(filename=filename, infer_table_structure=True)
        except:
            elements = []

        pdf_info = filename.split('\\')[-1].replace('.pdf', '').split('.')

        tables, tableidx = PDFReader.retrieve_table(elements)

        text = ''
        # append text which is not in tableidx
        for idx in range(len(elements)):
            if idx not in tableidx and elements[idx].category not in ['Image', 'FigureCaption']:
                text += '\n' + elements[idx].text
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        text_chunks = text_splitter.split_text(text)

        doc = []

        for chunk in text_chunks:
            content_cleanse = PDFReader.cleanse_text(chunk)

            if sum([x in content_cleanse for x in ['compliance', 'Compliance'
                , '무단 복제 및 배포', '투자의견 및 목표주가', '신의 성실', '외부의 부당한 압력', '허락없이 복사'
                , '투자자의 투자판단', '분포 고지', '고지 사항']]) > 0:
                continue

            new_doc = Document(
                page_content=content_cleanse,
                metadata={"doc_name": pdf_info[3], "class": pdf_info[2], "analyst": pdf_info[0], "date": pdf_info[1], "type": "text"}
            )
            doc.append(new_doc)

        # append tables
        for table in tables:
            content_cleanse = PDFReader.cleanse_text(table)

            if sum([x in content_cleanse for x in ['compliance', 'Compliance'
                , '무단 복제 및 배포', '투자의견 및 목표주가', '신의 성실', '외부의 부당한 압력', '허락없이 복사'
                , '투자자의 투자판단', '분포 고지', '고지 사항']]) > 0:
                continue

            new_doc = Document(
                page_content=content_cleanse,
                metadata={"doc_name": pdf_info[3], "class": pdf_info[2], "analyst": pdf_info[0], "date": pdf_info[1], "type": "table"}
            )
            doc.append(new_doc)

        return doc

    @staticmethod
    def fun_partion_pdf_simple(filename, metadata=None):
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*CropBox.*")
                elements = partition_pdf(filename=filename, strategy="fast")
        except:
            elements = []

        if metadata is None:
            pdf_info = filename.split('\\')[-1].replace('.pdf', '').split('.')
        else:
            pdf_info = metadata

        text = ''
        # append text which is not in tableidx
        for idx in range(len(elements)):
            if elements[idx].category not in ['Header', 'Footer']:
                text += '\n' + elements[idx].text
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=500)
        text_chunks = text_splitter.split_text(text)

        doc = []

        for chunk in text_chunks:
            content_cleanse = PDFReader.cleanse_text(chunk)

            if sum([x in content_cleanse for x in ['compliance', 'Compliance'
                , '무단 복제 및 배포', '투자의견 및 목표주가', '신의 성실', '외부의 부당한 압력', '허락없이 복사'
                , '투자자의 투자판단', '분포 고지', '고지 사항']]) > 0:
                continue

            new_doc = Document(
                page_content=content_cleanse,
                metadata={"doc_name": pdf_info[3], "class": pdf_info[2], "analyst": pdf_info[0], "date": pdf_info[1], "type": "text"}
            )
            doc.append(new_doc)

        return doc

    @staticmethod
    def fun_partion_text(text):
        # append text which is not in tableidx
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=500)
        text_chunks = text_splitter.split_text(text)

        return text_chunks

    def getPDF(self, pdflist:List, multiprocessing:bool=True):
        '''
        지정된 경로의 PDF 문서들의 텍스트 값을 가져옵니다.

        :param filelist: PDF 문서 목록
        :param sample: PDF 문서 전체 중 일부 비율만을 추출
        :return:
        '''
        if multiprocessing:
            #pdflist 기준 multiprocessing으로 병렬 처리
            Docset = process_map(PDFReader.fun_partion_pdf_simple, pdflist, max_workers=os.cpu_count()-1, desc='PDF 추출 - It might takes a lot of time', chunksize=1)
            Docset = [doc for sublist in Docset for doc in sublist]  # flatten the list
        else:
            #pdflist 기준 순차적으로 처리
            Docset = []
            for pdf in tqdm(pdflist, desc='PDF 추출 - It might takes a lot of time'):
                doc = PDFReader.fun_partion_pdf_simple(pdf)
                Docset.extend(doc)

        return Docset

if __name__ == '__main__':
    # Load the data
    pdflist = glob('C:/Users/NHWM/PycharmProjects/AllocateGPT/data/pdf_logs/*.pdf')
    pr = PDFReader()
    docList = pr.getPDF(pdflist[:3], True)
    c = 1
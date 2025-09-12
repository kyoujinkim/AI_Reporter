# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

이 프로젝트는 기업의 실적 발표 자료를 기준으로 기존 예측치 상회/하회 여부를 분석하고, 다양한 시나리오를 생성하는 AI 기반 시스템입니다.
사용할 수 있는 데이터는 다음과 같습니다.
- 기업의 내용 : ./data/summary/company_business.md
- 실적발표와 과거 추정치 비교 : ./data/summary/earnings_analysis.md
- 재무제표 분석 : ./data/summary/financial_analysis.md
- IR 발표자료 요약 : ./data/summary/ir_summary.md
- 다음 분기 실적 추정치: ./data/consensus_analysis.md

AI 시스템의 목적은 이 데이터를 종합하여 다음과 같은 작업을 수행하는 것입니다.
1. 실적 발표 결과가 기존 예측치를 상회/하회한 이유 분석
2. 향후 실적에 대한 다양한 시나리오 생성 (예: 낙관적, 비관적, 중립적)
3. 각 시나리오에 대한 근거 및 설명 제공
4. 최종 보고서 작성 (마크다운 형식)
5. 차트 생성 (막대, 선, 파이, 산점도 등)

## Core Architecture

### Key Tools (`src/tools/`)
- 필요하다면 Tavily API와 인간의 중간 개입을 요청할 수 있습니다.

### AI Model Configuration
- Default model: `gpt-4.1-mini` (configurable in agent classes)
- PDF analysis uses: `gpt-4o-mini` for vision tasks
- Summarizer uses token-aware chunking with 4000 token chunks, 2000 token summaries

### Chart Generation
The system includes a sophisticated chart generation tool (`make_chart`) that supports:
- Multiple chart types (bar, line, pie, scatter, area)
- Multi-series data with secondary y-axis
- Data labels and customizable styling
from enum import Enum


class PresentationType(str, Enum):
    """프레젠테이션(팀) 유형 — 단일 선택."""

    schoolTeamProject = "schoolTeamProject"  # 학교 팀프로젝트 발표
    companyPtInterview = "companyPtInterview"  # 기업 PT 면접
    executiveReport = "executiveReport"  # 직장 임원보고
    etc = "etc"  # 그 외


class AudienceType(str, Enum):
    """청중(질문자) 유형."""

    teto = "teto"  # 테토청중
    egen = "egen"  # 에겐청중
    kkondae = "kkondae"  # 꼰대청중
    etc = "etc"  # 기타
